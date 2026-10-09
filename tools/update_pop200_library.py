"""Fixed POP200 add-only update: 132 -> 332, for the existing local library.

Preflight is the default; --apply is explicit. Only 200 NEW score files per
location and the two backed-up catalogues may be installed. UserData is hashed,
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
OLD_COUNT = 132
NEW_COUNT = 200
FINAL_COUNT = 332
POP_COMMIT = 'd83e6edba6872a704f5d3b8b32f5cb540088dae6'
POP_URL = 'https://github.com/music-x-lab/POP909-Dataset/blob/' + POP_COMMIT
REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


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


def _validate_new(id_, entry, row, columns, staged):
    rel, digest, metadata = entry
    match = re.fullmatch(r'pop909-(\d{3})\.json', rel)
    if not match or not 1 <= int(match[1]) <= 909 or id_ != 'builtin:' + rel:
        raise ValueError('New entries must be POP909 resources with stable builtin IDs: ' + id_)
    prov = metadata.get('provenance')
    if not isinstance(prov, dict):
        raise ValueError('Missing new provenance: ' + rel)
    artists = prov.get('artists')
    if (not isinstance(artists, list) or not artists or
            any(not isinstance(artist, str) or not artist.strip() for artist in artists) or
            len({_title_key(artist) for artist in artists}) != len(artists)):
        raise ValueError('Nonempty, distinct source artists required: ' + rel)
    if (prov.get('synthetic') is not False or prov.get('redistributionVerified') is not False or
            prov.get('musicReview') != 'not-reviewed' or prov.get('gameReview') != 'not-tested' or
            prov.get('timingStatus') != 'source-compared' or prov.get('provider') != 'POP909'):
        raise ValueError('Missing source comparison or misleading review classification: ' + rel)
    source_hash = _digest(prov.get('sourceSha256'), rel + ' source')
    sid = match[1]
    if prov.get('sourceUrl') != f'{POP_URL}/POP909/{sid}/{sid}.mid':
        raise ValueError('New source identity must use the fixed POP909 source: ' + rel)
    if (_digest(metadata.get('hash'), rel + ' original hash') != source_hash or
            _digest(metadata.get('resourceHash'), rel + ' resource hash') != digest):
        raise ValueError('New metadata/source/resource hash mismatch: ' + rel)
    if not isinstance(metadata.get('options'), dict):
        raise ValueError('Missing new catalogue defaults: ' + rel)
    for key in ('id', 'catalogId'):
        if key in metadata and metadata[key] != id_:
            raise ValueError('New metadata ID mismatch: ' + rel)
    values = dict(zip(columns, row))
    if 'original_hash' in values and _digest(values['original_hash'], rel + ' catalogue original') != source_hash:
        raise ValueError('New catalogue original/source hash mismatch: ' + rel)
    if 'work_id' in values and values['work_id'] != prov.get('workId'):
        raise ValueError('New catalogue work identity mismatch: ' + rel)
    score = _json((staged / rel).read_text(encoding='utf-8-sig'))
    if not isinstance(score, dict) or score.get('title') != metadata.get('title') or score.get('provenance') != prov:
        raise ValueError('New metadata differs from normalized source score: ' + rel)
    _title_key(metadata.get('title'))


def validate_update(staged, targets):
    incoming = read_catalog(staged)
    old_catalogs = [read_catalog(target) for target in targets]
    if len(incoming.entries) != FINAL_COUNT or any(len(old.entries) != OLD_COUNT for old in old_catalogs):
        raise ValueError('This batch requires runtime/source 132 each and stage 332 exactly')
    baseline = old_catalogs[0]
    for old in old_catalogs:
        if (old.columns != incoming.columns or old.search_columns != incoming.search_columns or
                old.meta_rows != incoming.meta_rows):
            raise ValueError('Would change original catalogue schema/classification')
        if old.rows != baseline.rows or old.search_rows != baseline.search_rows:
            raise ValueError('Runtime/source original 132 entries differ')
        for id_, row in old.rows.items():
            if incoming.rows.get(id_) != row:
                raise ValueError('Would drop/change existing score/metadata/defaults/ID: ' + id_)
            if old.search_rows and incoming.search_rows.get(id_) != old.search_rows[id_]:
                raise ValueError('Would change existing search metadata: ' + id_)
    new_ids = sorted(set(incoming.entries) - set(baseline.entries))
    if len(new_ids) != NEW_COUNT:
        raise ValueError('Exactly 200 new POP909 IDs are required')
    old_titles = {_title_key(entry[2].get('title')) for entry in baseline.entries.values()}
    new_titles = set()
    for id_ in new_ids:
        entry = incoming.entries[id_]
        _validate_new(id_, entry, incoming.rows[id_], incoming.columns, staged)
        title = _title_key(entry[2].get('title'))
        if title in old_titles or title in new_titles:
            raise ValueError('Duplicate new/old title: ' + entry[2]['title'])
        new_titles.add(title)
    operations = []
    for target in targets:
        existing = {path.name.casefold() for path in target.iterdir()}
        added = [incoming.entries[id_][0] for id_ in new_ids]
        for rel in added:
            if rel.casefold() in existing:
                raise FileExistsError('New score path already exists (no automatic resume/overwrite): ' + str(target / rel))
        operations.append({'target': str(target), 'oldEntries': OLD_COUNT,
                           'newEntries': FINAL_COUNT, 'addFiles': sorted(added)})
    return incoming, old_catalogs, new_ids, operations


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


def _paths(staged, runtime, source, backup, report):
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
    for i, left in enumerate(paths):
        for right in paths[i + 1:]:
            if _overlap(left, right):
                raise ValueError('Stage/runtime/source/backup/report must not overlap: ' + str(left) + ' / ' + str(right))
    staged, runtime, source, backup, report = paths
    for path in (staged, runtime, source, runtime / 'Songs'):
        if not stat.S_ISDIR(_plain(path).st_mode):
            raise ValueError('Missing input directory: ' + str(path))
    if source.name != 'Songs' or runtime.parent.name != 'dist':
        raise ValueError('Expected source Songs and an existing runtime under dist')
    sha(runtime / 'QinBan.exe')
    for path in (backup, report):
        if _exists(path):
            raise FileExistsError('Use NEW, nonexistent backup/report paths; refusing overwrite: ' + str(path))
    return staged, runtime, source, backup, report


def preflight(staged, runtime, source, backup, report):
    staged, runtime, source, backup, report = _paths(staged, runtime, source, backup, report)
    before = {'runtime': tree_state(runtime), 'source': tree_state(source)}
    stage_state = tree_state(staged)
    incoming, old_catalogs, new_ids, operations = validate_update(staged, (runtime / 'Songs', source))
    plan = {'staged': staged, 'runtime': runtime, 'source': source, 'backup': backup,
            'report': report, 'before': before, 'stageState': stage_state,
            'incoming': incoming, 'oldCatalogs': old_catalogs, 'newIds': new_ids,
            'operations': operations}
    _assert_live(plan, [], set())
    _require_quiet()
    return plan


def _assert_live(plan, created, switched):
    for path in (plan['staged'], plan['runtime'], plan['source'], plan['backup'], plan['report']):
        _ancestors(path)
    if tree_state(plan['staged']) != plan['stageState']:
        raise ValueError('Staged files/catalogue changed after preflight')
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
            'source': str(plan['staged']), 'derivedFrom': 'validated staged 332-entry catalogue',
            'scores': [{'id': id_, 'relativePath': rel, 'contentSha256': digest}
                       for id_, (rel, digest, _) in sorted(incoming.entries.items())]}


def _base_result(plan):
    return {'atUtc': datetime.now(timezone.utc).isoformat(), 'preflightReady': True,
            'runtime': str(plan['runtime']), 'source': str(plan['source']),
            'backup': str(plan['backup']), 'operations': plan['operations'],
            'manifest': _manifest(plan), 'newBuiltinCount': len(plan['incoming'].entries),
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
            active = ('original-132' if current == original_hash else
                      'staged-332' if current == plan['stageState']['files']['catalog.db'] else 'changed-unknown')
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


def deploy(staged, runtime, source, backup, report, apply=False):
    plan = preflight(staged, runtime, source, backup, report)
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
                          addedScoresPerTarget=NEW_COUNT, after=after, oldMetadataIdsDefaultsUnchanged=True,
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
                                                   if item['catalogState'] == 'original-132'],
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
    parser.add_argument('--apply', action='store_true', help='Otherwise preflight only; writes only a new report')
    args = parser.parse_args(argv)
    try:
        result = deploy(args.staged_songs, args.runtime, args.source_songs,
                        args.backup, args.report, args.apply)
    except Exception as error:
        print('PREFLIGHT/UPDATE FAILED: ' + repr(error), file=sys.stderr)
        return 1
    print(result['status'] + ': 132 -> 332; exactly 200 new POP909 scores per target; ' + args.runtime)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
