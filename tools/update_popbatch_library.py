"""Provider-agnostic, add-only update for a validated source batch and local library.

Preflight is the default; --apply is explicit. Only the NEW score files in the
staged catalogue and the two backed-up catalogues may be installed. UserData is hashed,
never opened as SQLite or restored. All evidence destinations must be NEW.
Failure keeps even partial new files and records guarded catalogue-only recovery.
There is deliberately no resume/cleanup/download/process-termination mode.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
MANIFEST_FILENAMES = ('input-manifest.json', 'build-manifest.json', 'manifest.json')
MANIFEST_ENTRY_ALIASES = (
    ('songs', 'Songs'),
    ('entries', 'Entries'),
    ('records', 'Records'),
    ('scores', 'Scores'),
    ('items', 'Items'),
)
MANIFEST_ENTRY_KEYS = tuple(name for aliases in MANIFEST_ENTRY_ALIASES for name in aliases)
MANIFEST_PROVIDER_ALIASES = ('provider', 'Provider')
MANIFEST_ID_ALIASES = ('id', 'Id')
MANIFEST_PROVENANCE_ALIASES = ('provenance', 'Provenance')
STABLE_BUILTIN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*-[A-Za-z0-9][A-Za-z0-9._-]*\.json$')
_MISSING = object()
_NO_DEFAULT = object()
REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
CHINESE_LANGUAGE_BASES = {'zh', 'cmn', 'yue'}
CHINESE_POP_TAGS = {
    '\u4e2d\u6587\u6b4c\u66f2', '\u4e2d\u6587\u6d41\u884c', '\u4e2d\u6587\u6d41\u884c\u5019\u9009',
    '\u7ca4\u8bed\u6b4c\u66f2', '\u7ca4\u8bed\u6d41\u884c', '\u7ca4\u8bed\u6d41\u884c\u5019\u9009',
}


def _enforce_language_policy(provenance, relative, policy):
    """Reject an incoming batch that does not explicitly belong to the selected language lane."""
    if policy == 'none':
        return
    if policy not in {'chinese-pop-first', 'chinese-pop-main'}:
        raise ValueError('Unknown language policy: ' + str(policy))
    language_tags = provenance.get('languageTags')
    if not isinstance(language_tags, list) or not language_tags:
        raise ValueError('language policy requires explicit languageTags: ' + relative)
    bases = {str(tag).strip().lower().split('-', 1)[0] for tag in language_tags if isinstance(tag, str) and tag.strip()}
    if not bases or not bases.issubset(CHINESE_LANGUAGE_BASES):
        raise ValueError('language policy requires only zh/cmn/yue languageTags: ' + relative)
    tags = provenance.get('tags')
    if not isinstance(tags, list) or not CHINESE_POP_TAGS.intersection(tags):
        raise ValueError('language policy requires explicit Chinese/Cantonese pop tags: ' + relative)
    if policy == 'chinese-pop-main' and '\u5927\u4f17\u4f18\u5148' not in tags:
        raise ValueError('chinese-pop-main requires the explicit priority tag: ' + relative)


def _plain(path):
    """lstat, never follow symlinks/junctions, including dangling links."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & REPARSE_POINT:
        raise ValueError('Links/junctions/reparse points are forbidden: ' + str(path))
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError('Hard-linked files are forbidden: ' + str(path))
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError('Unsupported filesystem object: ' + str(path))
    return info


def _exists(path):
    return os.path.lexists(path)


def _ancestors(path):
    for item in reversed((path, *path.parents)):
        if _exists(item):
            _plain(item)


def _signature(info):
    # Windows lstat adds execute bits by .exe extension; fstat has no filename.
    # Keep identity, size, time, file type and read/write-mode race checks.
    mode = info.st_mode & ~0o111 if os.name == 'nt' else info.st_mode
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, mode)


def sha(path):
    path = Path(path)
    before = _plain(path)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('Expected a regular file: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise ValueError('File raced before hashing: ' + str(path))
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise ValueError('File changed during hashing: ' + str(path))
    if _signature(_plain(path)) != _signature(before):
        raise ValueError('File replaced during hashing: ' + str(path))
    return digest.hexdigest().upper()


def tree_state(root):
    """Full inventory, not merely the catalogue/EXE or a historical backup."""
    root = Path(root)
    _ancestors(root)
    state = {'files': {}, 'fileModes': {}, 'directories': {}}

    def visit(directory):
        info = _plain(directory)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Expected directory: ' + str(directory))
        rel = directory.relative_to(root).as_posix()
        state['directories'][rel] = stat.S_IMODE(info.st_mode)
        with os.scandir(directory) as scan:
            paths = sorted((Path(item.path) for item in scan), key=lambda p: p.name)
        for path in paths:
            info = _plain(path)
            if stat.S_ISDIR(info.st_mode):
                visit(path)
            else:
                rel = path.relative_to(root).as_posix()
                state['files'][rel] = sha(path)
                state['fileModes'][rel] = stat.S_IMODE(info.st_mode)
    visit(root)
    return state


def snapshot(root):
    return tree_state(root)['files']


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json(raw):
    def invalid(value):
        raise ValueError('Non-finite JSON value: ' + value)
    return json.loads(raw, object_pairs_hook=_json_object, parse_constant=invalid)


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value):
        raise ValueError('Invalid SHA256: ' + label)
    return value.upper()


def _relative_score(value):
    if (not isinstance(value, str) or not value.endswith('.json') or
            re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or
            Path(value).name != value or value.rstrip(' .') != value):
        raise ValueError('Invalid flat score resource path: ' + repr(value))
    # Keep Windows path semantics even when fixtures run on another platform.
    stem = value.split('.')[0].upper()
    if stem in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Reserved Windows resource path: ' + value)
    return value


def _identity_text(value, label, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError('Expected string: ' + label)
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid whitespace/control characters: ' + label)
    if not allow_empty and not value:
        raise ValueError('Missing nonempty value: ' + label)
    return value


def _provider_slug(provider):
    provider = _identity_text(provider, 'provider')
    normalized = unicodedata.normalize('NFKC', provider).casefold()
    slug = re.sub(r'[^a-z0-9]+', '-', normalized).strip('-')
    if not slug:
        raise ValueError('Provider has no stable filename slug: ' + provider)
    return slug


def _stable_builtin_relative(value, label):
    value = _relative_score(value)
    if not STABLE_BUILTIN_RE.fullmatch(value):
        raise ValueError('Builtin resource must be a provider/stable-id manifest-derived filename: ' + value)
    return value


def _manifest_alias_value(mapping, names, label, *, default=_NO_DEFAULT):
    """Read one logical field without silently accepting conflicting aliases."""
    present = [(name, mapping[name]) for name in names if name in mapping]
    if not present:
        if default is not _NO_DEFAULT:
            return default
        raise ValueError('Manifest is missing ' + label)
    first_name, first_value = present[0]
    for name, value in present[1:]:
        if value != first_value:
            raise ValueError(
                'Conflicting manifest aliases for ' + label + ': ' +
                first_name + ' vs ' + name
            )
    return first_value


def _manifest_nested(record):
    nested = _manifest_alias_value(
        record, MANIFEST_PROVENANCE_ALIASES, 'provenance', default=None
    )
    return nested if isinstance(nested, dict) else {}


def _manifest_value(record, names, label, *, allow_empty=False):
    nested = _manifest_nested(record)
    values = []
    direct = _manifest_alias_value(record, names, label, default=_MISSING)
    if direct is not _MISSING:
        values.append(direct)
    nested_value = _manifest_alias_value(nested, names, label, default=_MISSING)
    if nested_value is not _MISSING:
        values.append(nested_value)
    if not values:
        raise ValueError('Manifest is missing ' + label)
    value = values[0]
    if any(other != value for other in values[1:]):
        raise ValueError('Conflicting manifest values for ' + label)
    return _identity_text(value, label, allow_empty=allow_empty)


def _has_provider_prefix(identifier, slug):
    """Accept separator variants without duplicating the provider in a filename.

    A provider such as ``OpenScoreLieder`` can legitimately emit stable IDs such
    as ``openscore-lieder-123``.  Comparing only the literal slug would turn
    that into ``openscorelieder-openscore-lieder-123.json``.  The boundary check
    still rejects a bare prefix inside an alphanumeric token (for example
    provider ``PDMX`` and ID ``pdmxfoo``).
    """
    wanted = re.sub(r'[^a-z0-9]+', '', slug.casefold())
    if not wanted:
        return False
    consumed = 0
    boundary = None
    for index, char in enumerate(identifier.casefold()):
        if char.isalnum():
            consumed += 1
            if consumed == len(wanted):
                boundary = index + 1
                break
    if boundary is None:
        return False
    return boundary == len(identifier) or not identifier[boundary].isalnum()


def _manifest_relative(record, provider, manifest_path):
    direct_fields = (
        ('relativePath', ('relativePath', 'relative_path', 'RelativePath')),
        ('scoreFile', ('scoreFile', 'score_file', 'ScoreFile')),
        ('file', ('file', 'File')),
        ('builtinId', ('builtinId', 'builtin_id', 'BuiltinId')),
        ('catalogId', ('catalogId', 'catalog_id', 'CatalogId')),
    )
    for label, names in direct_fields:
        value = _manifest_alias_value(record, names, f'{manifest_path} {label}', default=_MISSING)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if value.startswith('builtin:'):
                value = value[len('builtin:'):]
            if not value.endswith('.json'):
                value += '.json'
            return _stable_builtin_relative(value, f'{manifest_path} {label}')
    identifier = _manifest_alias_value(record, MANIFEST_ID_ALIASES,
                                        f'{manifest_path} id', default=None)
    identifier = _identity_text(identifier, f'{manifest_path} id')
    if identifier.startswith('builtin:'):
        identifier = identifier[len('builtin:'):]
    if identifier.endswith('.json'):
        return _stable_builtin_relative(identifier, f'{manifest_path} id')
    slug = _provider_slug(provider)
    stem = identifier if _has_provider_prefix(identifier, slug) else slug + '-' + identifier
    return _stable_builtin_relative(stem + '.json', f'{manifest_path} id')


def _manifest_candidates(root):
    root = Path(root)
    _ancestors(root)
    info = _plain(root)
    if stat.S_ISREG(info.st_mode):
        if root.suffix.casefold() != '.json':
            raise ValueError('Manifest path must be a JSON file: ' + str(root))
        return [root]
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Manifest root must be a directory or JSON file: ' + str(root))
    return [root / name for name in MANIFEST_FILENAMES if _exists(root / name)]


def _read_manifest_json(path):
    before = sha(path)
    try:
        raw = Path(path).read_text(encoding='utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('Manifest is not strict UTF-8: ' + str(path)) from error
    value = _json(raw)
    if sha(path) != before:
        raise ValueError('Manifest raced during read: ' + str(path))
    return value, before


def _optional_manifest_sha(record, names, label):
    nested = _manifest_nested(record)
    direct = _manifest_alias_value(record, names, label, default=_MISSING)
    nested_value = _manifest_alias_value(nested, names, label, default=_MISSING)
    values = [value for value in (direct, nested_value) if value is not _MISSING]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise ValueError('Conflicting manifest values for ' + label)
    return _digest(values[0], label)


def _load_manifest(path, kind):
    path = Path(path)
    raw, manifest_hash = _read_manifest_json(path)
    if isinstance(raw, list):
        top_provider = None
        records = raw
    elif isinstance(raw, dict):
        raw_provider = _manifest_alias_value(
            raw, MANIFEST_PROVIDER_ALIASES, f'{path} provider', default=None
        )
        top_provider = (_identity_text(raw_provider, str(path) + ' provider')
                        if raw_provider is not None else None)
        records = None
        for aliases in MANIFEST_ENTRY_ALIASES:
            candidate = _manifest_alias_value(
                raw, aliases, f'{path} entry list', default=_MISSING
            )
            if isinstance(candidate, list):
                records = candidate
                break
        if records is None:
            raise ValueError('Manifest has no supported entry list: ' + str(path))
    else:
        raise ValueError('Manifest root must be an object or array: ' + str(path))
    normalized = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError('Manifest entry must be an object: ' + str(path) + '[' + str(index) + ']')
        record_provider = _manifest_alias_value(
            record, MANIFEST_PROVIDER_ALIASES,
            f'{path} entry {index} provider', default=top_provider
        )
        if record_provider is None:
            nested = _manifest_nested(record)
            record_provider = _manifest_alias_value(
                nested, MANIFEST_PROVIDER_ALIASES,
                f'{path} entry {index} provider', default=None
            )
        record_provider = _identity_text(record_provider, f'{path} entry {index} provider')
        if top_provider is not None and record_provider != top_provider:
            raise ValueError('Manifest entry/provider mismatch: ' + str(path))
        relative = _manifest_relative(record, record_provider, path)
        if relative.casefold() in normalized:
            raise ValueError('Duplicate manifest resource path: ' + relative)
        values = {
            'provider': record_provider,
            'sourceUrl': _manifest_value(
                record, ('sourceUrl', 'source_url', 'SourceUrl'),
                f'{path} entry {index} sourceUrl'
            ),
            'sourceSha256': _digest(
                _manifest_value(
                    record, ('sourceSha256', 'source_sha256', 'SourceSha256',
                             'sourceSHA256', 'SourceSHA256'),
                    f'{path} entry {index} sourceSha256'
                ),
                f'{path} entry {index} sourceSha256'
            ),
            'notationSha256': _optional_manifest_sha(
                record, ('notationSha256', 'notation_sha256', 'NotationSha256',
                         'notationSHA256', 'NotationSHA256'),
                f'{path} entry {index} notationSha256'
            ),
            'workId': _manifest_value(
                record, ('workId', 'work_id', 'WorkId'),
                f'{path} entry {index} workId'
            ),
            'editionId': _manifest_value(
                record, ('editionId', 'edition_id', 'EditionId'),
                f'{path} entry {index} editionId'
            ),
            'versionLabel': _manifest_value(
                record, ('versionLabel', 'version_label', 'VersionLabel'),
                f'{path} entry {index} versionLabel', allow_empty=True
            ),
            'title': _manifest_alias_value(
                record, ('title', 'Title'), f'{path} entry {index} title', default=None
            ),
            'record': record,
        }
        normalized[relative.casefold()] = {'relativePath': relative, **values}
    return {
        'path': str(path),
        'kind': kind,
        'sha256': manifest_hash,
        'provider': top_provider,
        'records': normalized,
    }


def _manifest_identity(record):
    return (record['provider'], record['sourceUrl'], record['sourceSha256'].upper(),
            record['workId'], record['editionId'], record['versionLabel'])


def _manifest_source_path(record, source_root):
    if source_root is None:
        return None
    raw = record.get('record', {})
    source_fields = (
        ('midiPath', ('midiPath', 'midi_path', 'MidiPath')),
        ('sourcePath', ('sourcePath', 'source_path', 'SourcePath')),
        ('sourceFile', ('sourceFile', 'source_file', 'SourceFile')),
    )
    for label, names in source_fields:
        value = _manifest_alias_value(raw, names, label, default=_MISSING)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        candidate = Path(value)
        if candidate.is_absolute():
            full = Path(os.path.abspath(candidate))
        else:
            if '..' in candidate.parts:
                raise ValueError('Manifest source path traversal is forbidden: ' + value)
            full = Path(os.path.abspath(Path(source_root) / candidate))
        root = Path(os.path.abspath(source_root))
        if not full.is_relative_to(root):
            raise ValueError('Manifest source file escapes --source-root: ' + value)
        _ancestors(full)
        info = _plain(full)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Manifest source path is not a regular file: ' + str(full))
        observed = sha(full)
        expected_hash = (record.get('notationSha256') or record['sourceSha256']).upper()
        if observed != expected_hash:
            raise ValueError('Manifest source SHA mismatch: ' + str(full))
        return {'path': str(full), 'sha256': observed}
    return None


def _manifest_context(staged, source_root, requested_provider):
    stage_paths = _manifest_candidates(Path(staged).parent) + _manifest_candidates(Path(staged))
    source_paths = _manifest_candidates(source_root) if source_root is not None else []
    if source_root is not None and not source_paths:
        raise ValueError('No manifest found under --source-root: ' + str(source_root))
    seen = set()
    manifests = []
    for kind, paths in (('stage', stage_paths), ('source', source_paths)):
        for path in paths:
            key = str(Path(path).absolute()).casefold()
            if key in seen:
                continue
            seen.add(key)
            manifests.append(_load_manifest(path, kind))
    requested = (_identity_text(requested_provider, '--provider')
                 if requested_provider is not None else None)
    top_level_providers = {manifest['provider'] for manifest in manifests
                           if manifest['provider'] is not None}
    if requested is not None and any(value != requested for value in top_level_providers):
        raise ValueError('--provider disagrees with staged/source manifest provider')
    providers = set(top_level_providers)
    for manifest in manifests:
        providers.update(item['provider'] for item in manifest['records'].values())
    if requested is None and len(providers) > 1:
        raise ValueError('A batch cannot mix providers: ' + repr(sorted(providers)))
    expected = requested or (next(iter(providers)) if providers else None)
    if manifests and expected is None:
        raise ValueError('Manifest/provider identity is missing')
    for manifest in manifests:
        if manifest['provider'] is not None and manifest['provider'] != expected:
            raise ValueError('Manifest top-level provider mismatch: ' + manifest['path'])
    return {
        'provider': expected,
        'manifests': manifests,
        'manifestStates': [{'path': item['path'], 'sha256': item['sha256']} for item in manifests],
        'sourceStates': [],
        'stageManifestPaths': [item['path'] for item in manifests if item['kind'] == 'stage'],
        'sourceManifestPaths': [item['path'] for item in manifests if item['kind'] == 'source'],
    }


def _manifest_match(context, relative):
    matches = []
    for manifest in context['manifests']:
        item = manifest['records'].get(relative.casefold())
        if item is None:
            if manifest['kind'] == 'stage':
                raise ValueError('Stage manifest is missing new score: ' + relative)
            raise ValueError('Source manifest is missing new score: ' + relative)
        matches.append(item)
    if not matches:
        return None
    first = matches[0]
    identity = _manifest_identity(first)
    for item in matches[1:]:
        if _manifest_identity(item) != identity:
            raise ValueError('Stage/source manifest identity mismatch: ' + relative)
    if first['relativePath'].casefold() != relative.casefold():
        raise ValueError('Manifest resource path mismatch: ' + relative)
    return first


def _record_source_state(context, record, source_root):
    source_state = _manifest_source_path(record, source_root)
    if source_state is None:
        return
    if source_state not in context['sourceStates']:
        context['sourceStates'].append(source_state)


@dataclass
class Catalog:
    columns: tuple
    rows: dict
    entries: dict
    search_columns: tuple
    search_rows: dict
    meta_rows: list


def read_catalog(songs):
    """Only Songs/catalog.db is SQLite-opened, read-only and without sidecars."""
    songs = Path(songs)
    _ancestors(songs)
    catalog = songs / 'catalog.db'
    before = sha(catalog)
    for suffix in ('-wal', '-shm', '-journal'):
        if _exists(songs / ('catalog.db' + suffix)):
            raise ValueError('SQLite sidecar present; close/checkpoint the library first: ' + str(songs))
    connection = sqlite3.connect(catalog.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Corrupt catalogue: ' + str(catalog))
        cursor = connection.execute('SELECT * FROM entries')
        columns = tuple(field[0] for field in cursor.description)
        required = ('id', 'relative_path', 'content_hash', 'metadata_json')
        if not all(field in columns for field in required):
            raise ValueError('Missing catalogue entry columns')
        rows, entries, paths = {}, {}, set()
        for row in cursor.fetchall():
            values = dict(zip(columns, row))
            id_ = values['id']
            if not isinstance(id_, str) or not id_ or id_ in rows:
                raise ValueError('Invalid/duplicate catalogue ID: ' + repr(id_))
            rel = _relative_score(values['relative_path'])
            if rel.casefold() in paths:
                raise ValueError('Duplicate resource path: ' + rel)
            paths.add(rel.casefold())
            digest = _digest(values['content_hash'], rel)
            if sha(songs / rel) != digest:
                raise ValueError('Catalogue score checksum mismatch: ' + rel)
            metadata = _json(values['metadata_json'])
            if not isinstance(metadata, dict):
                raise ValueError('Catalogue metadata must be an object: ' + id_)
            rows[id_] = tuple(row)
            entries[id_] = (rel, digest, metadata)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        search_columns, search_rows = (), {}
        if 'search_index' in tables:
            cursor = connection.execute('SELECT * FROM search_index')
            search_columns = tuple(field[0] for field in cursor.description)
            if 'entry_id' not in search_columns:
                raise ValueError('Invalid search index schema')
            key = search_columns.index('entry_id')
            for row in cursor.fetchall():
                if row[key] not in entries or row[key] in search_rows:
                    raise ValueError('Invalid/duplicate search index entry')
                search_rows[row[key]] = tuple(row)
            if set(search_rows) != set(entries):
                raise ValueError('Incomplete catalogue search index')
        meta_rows = connection.execute('SELECT key,value FROM meta ORDER BY key').fetchall() if 'meta' in tables else []
        result = Catalog(columns, rows, entries, search_columns, search_rows, meta_rows)
    finally:
        connection.close()
    if sha(catalog) != before:
        raise ValueError('Catalogue raced during read: ' + str(catalog))
    return result


def _title_key(title):
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Missing/non-string title')
    return ' '.join(unicodedata.normalize('NFKC', title).casefold().split())


def _validate_new(id_, entry, row, columns, staged, *, expected_provider=None, manifest_record=None, language_policy='none'):
    rel, digest, metadata = entry
    if id_ != 'builtin:' + rel:
        raise ValueError('New entry ID must be builtin:<manifest-derived resource>: ' + id_)
    _stable_builtin_relative(rel, rel)
    prov = metadata.get('provenance')
    if not isinstance(prov, dict):
        raise ValueError('Missing new provenance: ' + rel)
    _enforce_language_policy(prov, rel, language_policy)
    artists = prov.get('artists')
    if (not isinstance(artists, list) or not artists or
            any(not isinstance(artist, str) or not artist.strip() for artist in artists) or
            len({_title_key(artist) for artist in artists}) != len(artists)):
        raise ValueError('Nonempty, distinct source artists required: ' + rel)
    if (prov.get('synthetic') is not False or prov.get('redistributionVerified') is not False or
            prov.get('musicReview') != 'not-reviewed' or prov.get('gameReview') != 'not-tested' or
            prov.get('timingStatus') != 'source-compared'):
        raise ValueError('Missing source comparison or misleading review classification: ' + rel)
    provider = _identity_text(prov.get('provider'), rel + ' provider')
    if expected_provider is not None and provider != expected_provider:
        raise ValueError('New provenance/provider mismatch: ' + rel)
    work_id = _identity_text(prov.get('workId'), rel + ' workId')
    edition_id = _identity_text(prov.get('editionId'), rel + ' editionId')
    version_label = _identity_text(prov.get('versionLabel'), rel + ' versionLabel', allow_empty=True)
    source_url = _identity_text(prov.get('sourceUrl'), rel + ' sourceUrl')
    source_hash = _digest(prov.get('sourceSha256'), rel + ' source')
    if manifest_record is not None:
        actual = (provider, source_url, source_hash, work_id, edition_id, version_label)
        expected = _manifest_identity(manifest_record)
        if actual != expected:
            raise ValueError('Provenance differs from stage/source manifest: ' + rel)
    if (_digest(metadata.get('hash'), rel + ' original hash') != source_hash or
            _digest(metadata.get('resourceHash'), rel + ' resource hash') != digest):
        raise ValueError('New metadata/source/resource hash mismatch: ' + rel)
    if not isinstance(metadata.get('options'), dict):
        raise ValueError('Missing new catalogue defaults: ' + rel)
    for key in ('id', 'catalogId'):
        if key in metadata and metadata[key] != id_:
            raise ValueError('New metadata ID mismatch: ' + rel)
    if 'relativePath' in metadata and metadata['relativePath'] != rel:
        raise ValueError('New metadata relative path mismatch: ' + rel)
    values = dict(zip(columns, row))
    if 'original_hash' in values and _digest(values['original_hash'], rel + ' catalogue original') != source_hash:
        raise ValueError('New catalogue original/source hash mismatch: ' + rel)
    if 'work_id' in values and values['work_id'] != work_id:
        raise ValueError('New catalogue work identity mismatch: ' + rel)
    score = _json((staged / rel).read_text(encoding='utf-8-sig'))
    if not isinstance(score, dict) or score.get('title') != metadata.get('title') or score.get('provenance') != prov:
        raise ValueError('New metadata differs from normalized source score: ' + rel)
    _title_key(metadata.get('title'))
    return provider, work_id, edition_id, version_label, source_hash


def validate_update(staged, targets, *, provider=None, source_root=None, language_policy='none'):
    incoming = read_catalog(staged)
    old_catalogs = [read_catalog(target) for target in targets]
    if len(old_catalogs) != 2:
        raise ValueError('Exactly runtime and source catalogues are required')
    old_count = len(old_catalogs[0].entries)
    final_count = len(incoming.entries)
    if old_count <= 0 or any(len(old.entries) != old_count for old in old_catalogs):
        raise ValueError('Runtime/source original catalogue counts differ or are empty')
    if final_count <= old_count:
        raise ValueError('Stage must strictly add entries over the existing baseline')
    baseline = old_catalogs[0]
    for old in old_catalogs:
        if (old.columns != incoming.columns or old.search_columns != incoming.search_columns or
                old.meta_rows != incoming.meta_rows):
            raise ValueError('Would change original catalogue schema/classification')
        if old.rows != baseline.rows or old.search_rows != baseline.search_rows:
            raise ValueError('Runtime/source original catalogue entries differ')
        for id_, row in old.rows.items():
            if incoming.rows.get(id_) != row:
                raise ValueError('Would drop/change existing score/metadata/defaults/ID: ' + id_)
            if old.search_rows and incoming.search_rows.get(id_) != old.search_rows[id_]:
                raise ValueError('Would change existing search metadata: ' + id_)
    new_ids = sorted(set(incoming.entries) - set(baseline.entries))
    expected_new = final_count - old_count
    if len(new_ids) != expected_new:
        raise ValueError('Stage delta does not equal final minus baseline entries')
    manifest_context = _manifest_context(staged, source_root, provider)
    old_title_work = {}
    old_source_hashes = set()
    old_edition_ids = set()
    baseline_paths = set()
    for entry in baseline.entries.values():
        rel, _, metadata = entry
        title = _title_key(metadata.get('title'))
        prov = metadata.get('provenance') or {}
        work_id = prov.get('workId')
        old_title_work.setdefault(title, set()).add(work_id)
        edition = prov.get('editionId')
        if isinstance(edition, str) and edition:
            old_edition_ids.add(edition)
        source = prov.get('sourceSha256')
        if isinstance(source, str) and re.fullmatch(r'[a-fA-F0-9]{64}', source):
            old_source_hashes.add(source.upper())
    new_titles = {}
    new_editions = set()
    new_source_hashes = set()
    batch_providers = set()
    for id_ in new_ids:
        entry = incoming.entries[id_]
        rel = entry[0]
        for manifest in manifest_context['manifests']:
            manifest_record_for_source = manifest['records'].get(rel.casefold())
            if manifest_record_for_source is not None:
                _record_source_state(manifest_context, manifest_record_for_source, source_root)
        manifest_record = _manifest_match(manifest_context, rel)
        validated = _validate_new(id_, entry, incoming.rows[id_], incoming.columns, staged,
                                  expected_provider=manifest_context['provider'],
                                  manifest_record=manifest_record, language_policy=language_policy)
        batch_provider, work_id, edition_id, version_label, source_hash = validated
        batch_providers.add(batch_provider)
        title = _title_key(entry[2].get('title'))
        if edition_id in new_editions or edition_id in old_edition_ids:
            raise ValueError('Duplicate editionId: ' + edition_id)
        if source_hash in old_source_hashes or source_hash in new_source_hashes:
            raise ValueError('Duplicate source SHA cannot create another edition: ' + title)
        # WorkId is the source contract for identifying a work. A same-title
        # entry with a different WorkId is allowed (for example, two artists'
        # songs with the same title). A same-title/same-WorkId addition is an
        # alternate edition and must be explicitly labelled.
        if title in old_title_work and work_id in old_title_work[title] and not version_label:
            raise ValueError('Exact title collision requires a labelled edition for the same WorkId: ' + entry[2]['title'])
        work_key = (title, work_id)
        if work_key in new_titles:
            prior_labels = new_titles[work_key]
            if not version_label or any(not label for label in prior_labels):
                raise ValueError('Exact new title collision requires labelled editions of one WorkId: ' + entry[2]['title'])
            prior_labels.append(version_label)
        else:
            new_titles[work_key] = [version_label]
        new_editions.add(edition_id)
        new_source_hashes.add(source_hash)
    if len(batch_providers) != 1:
        raise ValueError('New entries must use exactly one provider: ' + repr(sorted(batch_providers)))
    if manifest_context['provider'] is None:
        manifest_context['provider'] = next(iter(batch_providers))
    elif manifest_context['provider'] not in batch_providers:
        raise ValueError('Provider has no matching new entries: ' + manifest_context['provider'])
    operations = []
    for target in targets:
        existing = {path.name.casefold() for path in target.iterdir()}
        added = [incoming.entries[id_][0] for id_ in new_ids]
        for rel in added:
            if rel.casefold() in existing:
                raise FileExistsError('New score path already exists (no automatic resume/overwrite): ' + str(target / rel))
        operations.append({'target': str(target), 'oldEntries': old_count,
                           'newEntries': final_count, 'newEntriesThisBatch': expected_new, 'addFiles': sorted(added)})
    return incoming, old_catalogs, new_ids, operations, manifest_context

def active_instances():
    if os.name != 'nt':
        raise RuntimeError('QinBan process preflight requires this Windows host')
    command = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
               "$ErrorActionPreference='Stop'; "
               "$r=@(Get-Process -Name QinBan -ErrorAction SilentlyContinue | Select-Object Id,Path); "
               "if($r.Count -eq 0){'[]'}else{ConvertTo-Json -InputObject $r -Compress}")
    run = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                         capture_output=True, encoding='utf-8', errors='strict', check=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=30)
    values = _json(run.stdout)
    values = values if isinstance(values, list) else [values]
    if any(not isinstance(value, dict) or not isinstance(value.get('Id'), int) for value in values):
        raise RuntimeError('Untrustworthy QinBan process probe; refusing update')
    return values  # All QinBan instances, including unrelated/unknown/elevated paths.


def _require_quiet():
    active = active_instances()
    if active:
        raise RuntimeError('Close ALL QinBan instances first; none was stopped: ' + repr(active))


def _overlap(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _paths(staged, runtime, source, backup, report, source_root=None):
    workspace = Path(os.path.abspath(WORKSPACE))
    _ancestors(workspace)
    paths = []
    for value in (staged, runtime, source, backup, report):
        value = Path(value)
        if '..' in value.parts:
            raise ValueError('Parent traversal is forbidden: ' + str(value))
        path = Path(os.path.abspath(value))
        if path == workspace or not path.is_relative_to(workspace):
            raise ValueError('All paths must remain inside the named workspace: ' + str(path))
        _ancestors(path)
        paths.append(path)
    source_root_path = None
    if source_root is not None:
        source_root_path = Path(source_root)
        if '..' in source_root_path.parts:
            raise ValueError('Parent traversal is forbidden: ' + str(source_root_path))
        source_root_path = Path(os.path.abspath(source_root_path))
        if source_root_path == workspace or not source_root_path.is_relative_to(workspace):
            raise ValueError('Source root must remain inside the named workspace: ' + str(source_root_path))
        _ancestors(source_root_path)
        if not stat.S_ISDIR(_plain(source_root_path).st_mode):
            raise ValueError('Source root must be an existing directory: ' + str(source_root_path))
        paths.append(source_root_path)
    for i, left in enumerate(paths):
        for right in paths[i + 1:]:
            if _overlap(left, right):
                raise ValueError('Stage/runtime/source/source-root/backup/report must not overlap: ' +
                                 str(left) + ' / ' + str(right))
    staged, runtime, source, backup, report = paths[:5]
    for path in (staged, runtime, source, runtime / 'Songs'):
        if not stat.S_ISDIR(_plain(path).st_mode):
            raise ValueError('Missing input directory: ' + str(path))
    if source.name != 'Songs' or runtime.parent.name != 'dist':
        raise ValueError('Expected source Songs and an existing runtime under dist')
    sha(runtime / 'QinBan.exe')
    for path in (backup, report):
        if _exists(path):
            raise FileExistsError('Use NEW, nonexistent backup/report paths; refusing overwrite: ' + str(path))
    return staged, runtime, source, backup, report, source_root_path

def preflight(staged, runtime, source, backup, report, *, provider=None, source_root=None, language_policy='none'):
    staged, runtime, source, backup, report, source_root = _paths(
        staged, runtime, source, backup, report, source_root)
    before = {'runtime': tree_state(runtime), 'source': tree_state(source)}
    stage_state = tree_state(staged)
    incoming, old_catalogs, new_ids, operations, manifest_context = validate_update(
        staged, (runtime / 'Songs', source), provider=provider, source_root=source_root, language_policy=language_policy)
    plan = {'staged': staged, 'runtime': runtime, 'source': source, 'backup': backup,
            'report': report, 'sourceRoot': source_root, 'before': before,
            'stageState': stage_state, 'incoming': incoming, 'oldCatalogs': old_catalogs,
            'newIds': new_ids, 'operations': operations, 'manifestContext': manifest_context,
            'languagePolicy': language_policy,
            'manifestStates': manifest_context['manifestStates'],
            'sourceStates': manifest_context['sourceStates']}
    _assert_live(plan, [], set())
    _require_quiet()
    return plan

def _assert_live(plan, created, switched):
    for path in (plan['staged'], plan['runtime'], plan['source'], plan['backup'], plan['report']):
        _ancestors(path)
    if tree_state(plan['staged']) != plan['stageState']:
        raise ValueError('Staged files/catalogue changed after preflight')
    for item in plan.get('manifestStates', []):
        if sha(Path(item['path'])) != item['sha256']:
            raise ValueError('Manifest changed after preflight: ' + item['path'])
    for item in plan.get('sourceStates', []):
        if sha(Path(item['path'])) != item['sha256']:
            raise ValueError('Referenced source changed after preflight: ' + item['path'])
    actual = {}
    for label in ('runtime', 'source'):
        before = plan['before'][label]
        expected = {key: dict(values) for key, values in before.items()}
        for item in created:
            if item['target'] == label and item['complete']:
                expected['files'][item['relativePath']] = item['expectedSha256']
                expected['fileModes'][item['relativePath']] = item['mode']
        if label in switched:
            rel = 'Songs/catalog.db' if label == 'runtime' else 'catalog.db'
            expected['files'][rel] = plan['stageState']['files']['catalog.db']
        actual[label] = tree_state(plan[label])
        if actual[label] != expected:
            raise ValueError('Protected ' + label + ' inventory/hash/mode changed after preflight')
    return actual


def _new_parents(directory):
    _ancestors(directory)
    missing = []
    path = directory
    while not _exists(path):
        missing.append(path)
        path = path.parent
    for path in reversed(missing):
        path.mkdir()  # No exist_ok: a concurrent creator must be re-preflighted.
        _ancestors(path)


def _write_json(stream, value):
    json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())


def _write_json_new(path, value):
    _ancestors(path)
    with path.open('x', encoding='utf-8') as stream:
        _write_json(stream, value)


def _copy_exclusive(src, dst, expected, on_created=None):
    _ancestors(src)
    _ancestors(dst)
    if sha(src) != expected:
        raise ValueError('Copy source changed: ' + str(src))
    with src.open('rb') as inp, dst.open('xb') as out:
        if on_created:
            on_created(stat.S_IMODE(os.fstat(out.fileno()).st_mode))
        shutil.copyfileobj(inp, out)
        out.flush()
        os.fsync(out.fileno())
    if sha(dst) != expected or sha(src) != expected:
        raise ValueError('Copied resource checksum failed: ' + str(dst))


def atomic_copy(src, dst, *, temporary_root, expected_source, expected_destination,
                original_mode, before_replace=None, on_replaced=None):
    """Use a NEW backup-owned temp; never leave switch temporaries in Songs.

    A destination hash guard also applies to rollback, so a user's later catalogue
    is never replaced with the earlier backup. Read-only catalogue mode survives.
    """
    _ancestors(temporary_root)
    temp = temporary_root / ('catalog-switch-' + uuid.uuid4().hex + '.db')
    _copy_exclusive(src, temp, expected_source)
    os.chmod(temp, original_mode)
    if before_replace:
        before_replace()
    _ancestors(dst)
    if sha(dst) != expected_destination or stat.S_IMODE(_plain(dst).st_mode) != original_mode:
        raise ValueError('Catalogue changed immediately before atomic switch: ' + str(dst))
    readonly = not (original_mode & stat.S_IWRITE)
    replaced = False
    try:
        if readonly:
            os.chmod(dst, original_mode | stat.S_IWRITE)
        os.replace(temp, dst)
        replaced = True
        if on_replaced:
            on_replaced()
    finally:
        # Restore only this still-original catalogue's temporary writable bit.
        # If replacement succeeded, the pre-set temp mode is already correct.
        if readonly and not replaced and sha(dst) == expected_destination:
            os.chmod(dst, original_mode)


def _manifest(plan):
    incoming = plan['incoming']
    return {'entries': len(incoming.entries), 'newEntries': len(plan['newIds']),
            'catalogSha256': plan['stageState']['files']['catalog.db'],
            'source': str(plan['staged']), 'derivedFrom': 'validated staged additive catalogue',
            'scores': [{'id': id_, 'relativePath': rel, 'contentSha256': digest}
                       for id_, (rel, digest, _) in sorted(incoming.entries.items())]}


def _base_result(plan):
    context = plan['manifestContext']
    return {'atUtc': datetime.now(timezone.utc).isoformat(), 'preflightReady': True,
            'runtime': str(plan['runtime']), 'source': str(plan['source']),
            'sourceRoot': str(plan['sourceRoot']) if plan['sourceRoot'] is not None else None,
            'provider': context['provider'],
            'languagePolicy': plan['languagePolicy'],
            'stageManifestPaths': context['stageManifestPaths'],
            'sourceManifestPaths': context['sourceManifestPaths'],
            'backup': str(plan['backup']), 'operations': plan['operations'],
            'manifest': _manifest(plan), 'newBuiltinCount': len(plan['newIds']),
            'runtimeSnapshot': plan['before']['runtime']['files'],
            'sourceSnapshot': plan['before']['source']['files'],
            'actualUserDataDatabasesOpened': False, 'newDistributionFolderCreated': False,
            'nativeKeySendAttempts': 0, 'automaticResumeSupported': False}


def _catalog_info(plan, label):
    target = plan['runtime'] / 'Songs' if label == 'runtime' else plan['source']
    rel = 'Songs/catalog.db' if label == 'runtime' else 'catalog.db'
    return target, rel, plan['before'][label]['files'][rel], plan['before'][label]['fileModes'][rel]


def _rollback_catalogs(plan, attempts):
    rollback = []
    stage_hash = plan['stageState']['files']['catalog.db']
    for label in reversed(attempts):
        target, _, original_hash, mode = _catalog_info(plan, label)
        item = {'target': str(target), 'restored': False}
        try:
            current = sha(target / 'catalog.db')
            if current == original_hash:
                item.update(restored=True, action='already-original-no-write')
            elif current != stage_hash:
                raise ValueError('Rollback refused: active catalogue no longer has our installed hash')
            else:
                original = plan['backup'] / (label + '-catalog.db')
                if sha(original) != original_hash:
                    raise ValueError('Rollback refused: original catalogue backup hash changed')

                def guard():
                    _ancestors(target / 'catalog.db')
                    for suffix in ('-wal', '-shm', '-journal'):
                        if _exists(target / ('catalog.db' + suffix)):
                            raise ValueError('Rollback refused: catalogue sidecar appeared')
                    _require_quiet()
                atomic_copy(original, target / 'catalog.db', temporary_root=plan['backup'],
                            expected_source=original_hash, expected_destination=stage_hash,
                            original_mode=mode, before_replace=guard)
                if sha(target / 'catalog.db') != original_hash:
                    raise ValueError('Rollback catalogue verification failed')
                item.update(restored=True, action='restored-only-this-catalogue')
        except BaseException as error:
            item['error'] = repr(error)
        rollback.append(item)
    return rollback


def _recovery_state(plan, created):
    catalogs = {}
    for label in ('runtime', 'source'):
        target, _, original_hash, _ = _catalog_info(plan, label)
        try:
            current = sha(target / 'catalog.db')
            active = ('original-baseline' if current == original_hash else
                      'staged-catalogue' if current == plan['stageState']['files']['catalog.db'] else 'changed-unknown')
            if any(_exists(target / ('catalog.db' + suffix)) for suffix in ('-wal', '-shm', '-journal')):
                active = 'sidecar-present-unknown'
            catalogs[label] = {'state': active, 'sha256': current}
        except BaseException as error:
            catalogs[label] = {'state': 'unknown', 'error': repr(error)}
    observed = []
    for item in created:
        value = dict(item)
        try:
            value['observedSha256'] = sha(Path(item['path']))
            value['matchesExpected'] = value['observedSha256'] == value['expectedSha256']
        except BaseException as error:
            value['observationError'] = repr(error)
        value['catalogState'] = catalogs[item['target']]['state']
        observed.append(value)
    return catalogs, observed


def deploy(staged, runtime, source, backup, report, apply=False, *, provider=None, source_root=None, language_policy='none'):
    plan = preflight(staged, runtime, source, backup, report, provider=provider, source_root=source_root, language_policy=language_policy)
    result = _base_result(plan)
    _new_parents(plan['report'].parent)
    # Reserve a NEW report before any target writes; never overwrite a later file.
    with plan['report'].open('x', encoding='utf-8') as report_stream:
        if not apply:
            result.update(status='DRY-RUN-PASS', applied=False)
            _write_json(report_stream, result)
            return result
        created, attempts, switched = [], [], set()
        try:
            _ancestors(plan['backup'])
            _new_parents(plan['backup'].parent)
            plan['backup'].mkdir()  # Existing even-empty backups are forbidden.
            _assert_live(plan, [], set())
            _require_quiet()
            before_document = {'runtime': str(plan['runtime']), 'source': str(plan['source']),
                               'runtimeSnapshot': result['runtimeSnapshot'],
                               'sourceSnapshot': result['sourceSnapshot'],
                               'states': plan['before'], 'stageState': plan['stageState'],
                               'operations': plan['operations'], 'manifest': result['manifest']}
            _write_json_new(plan['backup'] / 'before.json', before_document)
            for label in ('runtime', 'source'):
                target, _, digest, _ = _catalog_info(plan, label)
                _copy_exclusive(target / 'catalog.db', plan['backup'] / (label + '-catalog.db'), digest)
            # Latest full inventories/process state again immediately before copying.
            _assert_live(plan, [], set())
            _require_quiet()
            for label in ('runtime', 'source'):
                target, _, _, _ = _catalog_info(plan, label)
                for id_ in plan['newIds']:
                    rel, digest, _ = plan['incoming'].entries[id_]
                    item = {'target': label, 'path': str(target / rel),
                            'relativePath': ('Songs/' if label == 'runtime' else '') + rel,
                            'expectedSha256': digest, 'complete': False}

                    def registered(mode, item=item):
                        item['mode'] = mode
                        created.append(item)  # Include partial files if copying raises.
                    _copy_exclusive(plan['staged'] / rel, target / rel, digest, registered)
                    item['complete'] = True
            for label in ('runtime', 'source'):
                target, _, original_hash, mode = _catalog_info(plan, label)

                def guard():
                    _assert_live(plan, created, switched)
                    _require_quiet()
                attempts.append(label)
                atomic_copy(plan['staged'] / 'catalog.db', target / 'catalog.db',
                            temporary_root=plan['backup'],
                            expected_source=plan['stageState']['files']['catalog.db'],
                            expected_destination=original_hash, original_mode=mode,
                            before_replace=guard, on_replaced=lambda label=label: switched.add(label))
            _assert_live(plan, created, switched)
            for label in ('runtime', 'source'):
                target, _, _, _ = _catalog_info(plan, label)
                if read_catalog(target) != plan['incoming']:
                    raise ValueError('Post-switch catalogue mismatch: ' + label)
            _require_quiet()
            final_states = _assert_live(plan, created, switched)
            after = {label: state['files'] for label, state in final_states.items()}
            result.update(status='PASS', applied=True, addedFiles=[item['path'] for item in created],
                          addedScoresPerTarget=len(plan['newIds']), after=after, oldMetadataIdsDefaultsUnchanged=True,
                          allPreviouslyExistingNonCatalogFilesUnchanged=True,
                          exactAllowedDeltaVerifiedForRuntimeAndSource=True,
                          exeUnchanged=after['runtime']['QinBan.exe'] == result['runtimeSnapshot']['QinBan.exe'],
                          userDataUnchanged=True,
                          catalogSha256=plan['stageState']['files']['catalog.db'],
                          runtimeCatalogReadOnly=not bool(_catalog_info(plan, 'runtime')[3] & stat.S_IWRITE))
            _write_json(report_stream, result)
            return result
        except BaseException as error:
            rollback = _rollback_catalogs(plan, attempts)
            catalogs, observed = _recovery_state(plan, created)
            result.update(status='FAIL', applied=False, error=repr(error), rollback=rollback,
                          catalogStates=catalogs, copiedNewFilesPreserved=observed,
                          newInactiveFilesPreserved=[item['path'] for item in observed
                                                   if item['catalogState'] == 'original-baseline'],
                          manualRecoveryRequired=bool(created) or any(not item['restored'] for item in rollback),
                          recoveryInstruction='No scores/UserData deleted or restored. Keep originals/backups; '
                          'manually verify every retained new-file hash and active catalogue before recovery. '
                          'Partial files are not usable; automatic resume is not implemented.')
            try:
                # A PASS report write may itself have failed; this descriptor is ours.
                report_stream.seek(0)
                report_stream.truncate()
                _write_json(report_stream, result)
            except BaseException as report_error:
                print('FAIL: cannot save reserved failure report: ' + repr(report_error) +
                      '; original failure: ' + repr(error), file=sys.stderr)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-songs', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--source-songs', required=True)
    parser.add_argument('--backup', required=True, help='NEW nonexistent backup directory')
    parser.add_argument('--report', required=True, help='NEW nonexistent JSON report')
    parser.add_argument('--provider', default=None, help='Expected provider; otherwise derive from manifest/provenance')
    parser.add_argument('--language-policy', choices=('none', 'chinese-pop-first', 'chinese-pop-main'), default='none',
                        help='Optional hard admission lane; chinese-pop-first requires explicit Chinese/Cantonese pop metadata')
    parser.add_argument('--source-root', default=None,
                        help='Optional existing source/manifest root used for identity and source-hash checks')
    parser.add_argument('--apply', action='store_true', help='Otherwise preflight only; writes only a new report')
    args = parser.parse_args(argv)
    try:
        result = deploy(args.staged_songs, args.runtime, args.source_songs,
                        args.backup, args.report, args.apply,
                        provider=args.provider, source_root=args.source_root, language_policy=args.language_policy)
    except Exception as error:
        print('PREFLIGHT/UPDATE FAILED: ' + repr(error), file=sys.stderr)
        return 1
    print(result['status'] + ': additive batch applied/preflight; ' + str(result.get('newBuiltinCount', '?')) + ' new builtin scores; ' + args.runtime)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
