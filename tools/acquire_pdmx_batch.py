"""Metadata-first PDMX batch intake.

The tool is isolated from product runtime code. It reads the pinned local PDMX
source, selects real records deterministically, streams matching MIDI and
metadata members from the complete tar archives, and writes a new evidence
folder. It never writes Songs, an EXE, UserData, or game/window input.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import tarfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

try:
    from smf_reference import parse_smf
except ModuleNotFoundError:
    from tools.smf_reference import parse_smf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT / "catalog-intake" / "pdmx-2026-10-06"
DEFAULT_RECORD_JSON = ROOT / ".validation" / "pdmx-record-15571083.json"
ZENODO_RECORD_ID = 15571083
ZENODO_RECORD_URL = "https://zenodo.org/records/15571083"
ZENODO_API_URL = "https://zenodo.org/api/records/15571083"
DATASET_TITLE = "PDMX: A Large-Scale Public Domain MusicXML Dataset for Symbolic Music Processing"
SOURCE_COMMIT = "zenodo-15571083-revision-4"
BATCH_KIND = "metadata-first-candidate-intake"

MAX_MIDI_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MIN_DURATION_MS = 90_000
MAX_DURATION_MS = 1_800_000
MIN_NOTES = 100
MAX_NOTES = 100_000

MISSING_TOKENS = {"", "NA", "N/A", "NULL", "NONE"}
TRUE_TOKENS = {"true", "1", "yes"}
FALSE_TOKENS = {"false", "0", "no"}
SOURCE_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Conservative source-quality signals. A flagged row is retained in the reject
# queue and is not silently promoted to a public/Grade-A candidate.
MOJIBAKE_RE = re.compile(r"(?:\ufffd|[ÃÂÅÆÇÐÑÌÎÏâðæçåï].|[\u0080-\u009f])")
MODERN_YEAR_RE = re.compile(r"\b(?:19[2-9]\d|20\d{2})\b")
MODERN_TEXT_RE = re.compile(
    r"\b(?:pop|rock|rap|hip[ -]?hop|r&b|k[ -]?pop|j[ -]?pop|edm|electronic|dance|anime|manga|"
    r"soundtrack|movie|film|television|tv|ost|video[ -]?game|game[ -]?music|bollywood|feat\.?|ft\.?|vocaloid|hatsune|taylor\s+swift|adele|ed\s+sheeran|justin\s+bieber|beyonce|rihanna|bruno\s+mars|billie\s+eilish|michael\s+jackson|the\s+beatles|coldplay|lady\s+gaga|ariana\s+grande)\b",
    re.IGNORECASE,
)
MODERN_GENRE_RE = re.compile(
    r"(?:pop|rock|rap|hip[ -]?hop|r&b|k[ -]?pop|j[ -]?pop|edm|electronic|dance|anime|"
    r"soundtrack|movie|film|television|tv|ost|video[ -]?game|bollywood)",
    re.IGNORECASE,
)

ARCHIVE_SPECS = (
    ("PDMX.complete.csv", "PDMX-download.json", "PDMX.csv"),
    ("subset_paths.complete.tar.gz", "subset_paths-download.json", "subset_paths.tar.gz"),
    ("mid.complete.tar.gz", "mid-download.json", "mid.tar.gz"),
    ("metadata.complete.tar.gz", "metadata-download.json", "metadata.tar.gz"),
)


class IntakeError(RuntimeError):
    """A safe, expected intake failure that must be reported."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _hash_file(path: Path) -> tuple[str, str, int]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest().upper(), size


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"无法读取 JSON：{path}: {exc}") from exc



def _empty_existing_manifest_index() -> dict[str, Any]:
    return {
        "manifestPaths": [],
        "manifestCount": 0,
        "songCount": 0,
        "sourceHashes": set(),
        "editionIds": set(),
        "workIds": set(),
        "workEditionIds": collections.defaultdict(set),
        "sourceOwners": {},
        "editionOwners": {},
    }


def _manifest_song_value(song: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in song:
            return song[name]
    return None


def _normalise_source_sha256(value: Any, *, context: str) -> str:
    text = _raw(value).strip()
    if not SOURCE_SHA256_RE.fullmatch(text):
        raise IntakeError(f"{context} has an invalid SourceSha256; expected 64 hexadecimal characters")
    return text.upper()


def _load_existing_manifest_index(manifest_paths: Iterable[Path | str] | Path | str | None) -> dict[str, Any]:
    """Load prior intake manifests for deterministic, hash-bound batch exclusion.

    SourceSha256 and EditionId are hard duplicate keys. WorkId is deliberately a
    soft grouping key: a new EditionId for an existing WorkId is retained and
    marked so alternate arrangements/versions can be collected without silently
    treating them as different works.
    """
    index = _empty_existing_manifest_index()
    if manifest_paths is None:
        return index
    if isinstance(manifest_paths, (Path, str)):
        paths = [manifest_paths]
    else:
        paths = list(manifest_paths)

    seen_paths: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        resolved = path.resolve()
        if resolved.is_dir():
            resolved = (resolved / "manifest.json").resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not resolved.is_file():
            raise IntakeError(f"existing intake manifest does not exist: {resolved}")
        payload = _read_json(resolved)
        if not isinstance(payload, dict):
            raise IntakeError(f"existing intake manifest must be a JSON object: {resolved}")
        songs = payload.get("Songs") if "Songs" in payload else payload.get("songs")
        if not isinstance(songs, list):
            raise IntakeError(f"existing intake manifest has no Songs list: {resolved}")

        index["manifestPaths"].append(str(resolved))
        index["manifestCount"] += 1
        for song_number, song in enumerate(songs, start=1):
            if not isinstance(song, dict):
                raise IntakeError(f"Songs[{song_number}] is not an object: {resolved}")
            context = f"{resolved} Songs[{song_number}]"
            source_sha = _normalise_source_sha256(
                _manifest_song_value(song, "SourceSha256", "sourceSha256"), context=context
            )
            edition_id = _raw(_manifest_song_value(song, "EditionId", "editionId")).strip()
            work_id = _raw(_manifest_song_value(song, "WorkId", "workId")).strip()
            if not edition_id:
                raise IntakeError(f"{context} is missing EditionId")
            if not work_id:
                raise IntakeError(f"{context} is missing WorkId")

            source_owner = index["sourceOwners"].get(source_sha)
            if source_owner is not None and source_owner["editionId"] != edition_id:
                raise IntakeError(
                    f"conflicting SourceSha256 identity in existing manifests: {source_sha} "
                    f"({source_owner['editionId']} != {edition_id})"
                )
            edition_owner = index["editionOwners"].get(edition_id)
            if edition_owner is not None and edition_owner["sourceSha256"] != source_sha:
                raise IntakeError(
                    f"conflicting EditionId identity in existing manifests: {edition_id} "
                    f"({edition_owner['sourceSha256']} != {source_sha})"
                )

            owner = {
                "sourceSha256": source_sha,
                "editionId": edition_id,
                "workId": work_id,
                "manifestPath": str(resolved),
            }
            index["sourceOwners"].setdefault(source_sha, owner)
            index["editionOwners"].setdefault(edition_id, owner)
            index["sourceHashes"].add(source_sha)
            index["editionIds"].add(edition_id)
            index["workIds"].add(work_id)
            index["workEditionIds"][work_id].add(edition_id)
            index["songCount"] += 1
    return index


def _existing_manifest_summary(index: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifestPaths": list(index.get("manifestPaths", [])),
        "manifestCount": int(index.get("manifestCount", 0)),
        "songCount": int(index.get("songCount", 0)),
        "uniqueSourceSha256": len(index.get("sourceHashes", set())),
        "uniqueEditionIds": len(index.get("editionIds", set())),
        "uniqueWorkIds": len(index.get("workIds", set())),
        "deduplicationPolicy": "SourceSha256 and EditionId are hard duplicate keys; WorkId is a soft grouping key and new editions are retained with an explicit marker.",
    }

def _write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except FileExistsError as exc:
        raise IntakeError(f"拒绝覆盖已有文件：{path}") from exc


def _write_text_new(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
    except FileExistsError as exc:
        raise IntakeError(f"拒绝覆盖已有文件：{path}") from exc


def _write_bytes_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
    except FileExistsError as exc:
        raise IntakeError(f"拒绝覆盖已有文件：{path}") from exc


def _raw(value: Any) -> str:
    """Preserve source text; never turn NA into a guessed value."""
    return "" if value is None else str(value)


CORE_TITLE_LIMIT = 180


def _bounded_core_title(value: Any) -> tuple[str, bool]:
    """Keep the runtime title within SongParser's limit without losing source evidence."""
    text = _raw(value).strip()
    if len(text) <= CORE_TITLE_LIMIT:
        return text, False
    suffix = "..."
    return text[:CORE_TITLE_LIMIT - len(suffix)].rstrip() + suffix, True


def _is_missing(value: Any) -> bool:
    return _raw(value).strip().upper() in MISSING_TOKENS


def _parse_bool(value: Any) -> bool | None:
    text = _raw(value).strip().casefold()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    return None


def _parse_float(value: Any) -> float | None:
    try:
        return float(_raw(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _normalise_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _raw(value)).strip().casefold()
    return " ".join(text.split())


def _slug(value: Any, fallback: str = "unknown") -> str:
    text = unicodedata.normalize("NFKC", _raw(value)).strip().casefold()
    parts: list[str] = []
    for char in text:
        if unicodedata.category(char)[0] in {"L", "N"}:
            parts.append(char)
        elif parts and parts[-1] != "-":
            parts.append("-")
    result = "".join(parts).strip("-")
    return (result[:120].rstrip("-")) or fallback


def _safe_source_path(value: Any, *, suffix: str | None = None) -> str:
    text = _raw(value).strip().replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    if re.match(r"^[A-Za-z]:/", text) or text.startswith("//"):
        raise IntakeError(f"非法 PDMX 相对路径：{value!r}")
    if not text or text.startswith("/"):
        raise IntakeError(f"非法 PDMX 相对路径：{value!r}")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise IntakeError(f"非法 PDMX 相对路径：{value!r}")
    normalised = path.as_posix()
    if suffix and not normalised.casefold().endswith(suffix.casefold()):
        raise IntakeError(f"PDMX 路径后缀不符合预期：{value!r}")
    return normalised


def _asset_stem(source_path: str) -> str:
    name = PurePosixPath(source_path).name
    stem = name.rsplit(".", 1)[0] if "." in name else name
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", stem)
    return safe or sha256_bytes(source_path.encode("utf-8"))[:16]


def _canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def _has_suspicious_text(value: Any) -> bool:
    text = _raw(value)
    if not text:
        return False
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        return True
    if any(0x80 <= ord(char) <= 0x9F for char in text):
        return True
    return bool(MOJIBAKE_RE.search(text))


def _modern_rights_signals(row: dict[str, Any]) -> list[str]:
    fields = {name: row.get(name) for name in ("title", "song_name", "artist_name", "composer_name", "genres", "tags")}
    all_text = " ".join(_raw(value) for value in fields.values() if not _is_missing(value))
    signals: list[str] = []
    if MODERN_YEAR_RE.search(all_text):
        signals.append("explicit-year")
    if MODERN_TEXT_RE.search(all_text):
        signals.append("modern-popular-text")
    genres = _raw(fields.get("genres"))
    if not _is_missing(genres) and MODERN_GENRE_RE.search(genres):
        signals.append("modern-genre")
    if _parse_bool(row.get("is_original")) is True:
        signals.append("source-marked-original")
    return list(dict.fromkeys(signals))


def _http_url_or_empty(value: Any) -> str:
    text = _raw(value).strip()
    return text if re.match(r"^https?://[^\\s]+$", text, re.IGNORECASE) else ""

def _ranking_key(row: dict[str, str]) -> tuple[Any, ...]:
    def negative_number(field: str) -> float:
        value = _parse_float(row.get(field, ""))
        return -(value if value is not None else 0.0)

    return (
        negative_number("rating"), negative_number("n_favorites"), negative_number("n_ratings"), negative_number("n_views"),
        _normalise_text(row.get("song_name") or row.get("title")), _normalise_text(row.get("title")),
        _normalise_text(row.get("artist_name")), _normalise_text(row.get("composer_name")),
        _safe_source_path(row["path"], suffix=".json"),
    )


def _load_subset_paths(source_root: Path) -> tuple[set[str], dict[str, Any]]:
    path = source_root / "source" / "subset_paths" / "no_license_conflict.txt"
    if not path.is_file():
        raise IntakeError(f"缺少 no_license_conflict 子集：{path}")
    values: set[str] = set()
    invalid: list[str] = []
    duplicate_count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = line.strip()
        if not value:
            continue
        try:
            normalised = _safe_source_path(value, suffix=".json")
        except IntakeError:
            invalid.append(f"line {line_number}: {value}")
            continue
        if normalised in values:
            duplicate_count += 1
        values.add(normalised)
    if invalid:
        raise IntakeError(f"no_license_conflict.txt 含非法路径（首项）：{invalid[0]}")
    return values, {"path": str(path.resolve()), "count": len(values), "duplicateLines": duplicate_count}


def _load_candidate_rows(source_root: Path, subset_paths: set[str]) -> tuple[list[dict[str, str]], dict[str, int], list[dict[str, Any]]]:
    csv_path = source_root / "source" / "PDMX.complete.csv"
    if not csv_path.is_file():
        raise IntakeError(f"缺少 PDMX.complete.csv：{csv_path}")
    counters: collections.Counter[str] = collections.Counter()
    rejected: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    required_columns = {
        "path", "metadata", "mid", "license", "license_url", "license_conflict",
        "title", "song_name", "artist_name", "composer_name", "song_length.seconds", "n_notes",
        "is_best_unique_arrangement", "subset:rated_deduplicated", "subset:all_valid",
    }
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing_columns = sorted(required_columns - set(reader.fieldnames or []))
        if missing_columns:
            raise IntakeError(f"PDMX.csv 缺少必需列：{', '.join(missing_columns)}")
        for row_number, raw_row in enumerate(reader, start=2):
            row = {str(key): _raw(value) for key, value in raw_row.items() if key is not None}
            try:
                source_path = _safe_source_path(row.get("path"), suffix=".json")
            except IntakeError:
                counters["rejected_invalid_path"] += 1
                continue
            if source_path not in subset_paths:
                continue
            counters["subset_matches"] += 1
            if source_path in seen_paths:
                counters["rejected_duplicate_csv_path"] += 1
                rejected.append({"stage": "metadata-selection", "row": row_number, "path": source_path, "reason": "duplicate CSV path"})
                continue
            seen_paths.add(source_path)

            def reject(reason: str, **extra: Any) -> None:
                counters[f"rejected_{reason}"] += 1
                detail = {"stage": "metadata-selection", "row": row_number, "path": source_path, "reason": reason}
                detail.update(extra)
                rejected.append(detail)

            suspicious_fields = [
                field for field in ("title", "song_name", "artist_name", "composer_name", "genres", "tags")
                if _has_suspicious_text(row.get(field))
            ]
            if suspicious_fields:
                reject("suspicious_text_encoding", fields=suspicious_fields)
                continue
            modern_signals = _modern_rights_signals(row)
            if modern_signals:
                reject("modern_or_popular_rights_signal", signals=modern_signals, reviewQueue="rights-review-required")
                continue
            if _raw(row.get("license")).strip().casefold() != "publicdomain":
                reject("license_not_publicdomain")
                continue
            if _parse_bool(row.get("license_conflict")) is not False:
                reject("license_conflict_not_false")
                continue
            if _parse_bool(row.get("subset:rated_deduplicated")) is not True:
                reject("not_rated_deduplicated")
                continue
            if _parse_bool(row.get("subset:all_valid")) is not True:
                reject("not_all_valid")
                continue
            if _parse_bool(row.get("is_best_unique_arrangement")) is not True:
                reject("not_best_unique_arrangement")
                continue
            if _is_missing(row.get("title")):
                reject("missing_title")
                continue
            if _is_missing(row.get("artist_name")): 
                reject("missing_artist")
                continue
            duration = _parse_float(row.get("song_length.seconds"))
            if duration is None or not 90 <= duration <= 1800:
                reject("duration_outside_90s_30m")
                continue
            notes = _parse_int(row.get("n_notes"))
            if notes is None or not MIN_NOTES <= notes <= MAX_NOTES:
                reject("note_count_outside_budget")
                continue
            try:
                _safe_source_path(row.get("mid"), suffix=".mid")
                _safe_source_path(row.get("metadata"), suffix=".json")
            except IntakeError:
                reject("invalid_mid_or_metadata_path")
                continue
            rows.append(row)
            counters["eligible_metadata_rows"] += 1
    rows.sort(key=_ranking_key)
    counters["csv_rows_read"] = counters.get("subset_matches", 0)
    return rows, dict(counters), rejected


def _read_tar_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, maximum: int) -> bytes:
    if not member.isfile():
        raise IntakeError(f"目标 tar 成员不是普通文件：{member.name}")
    if member.size < 0 or member.size > maximum:
        raise IntakeError(f"tar 成员大小超出预算：{member.name} ({member.size} bytes)")
    stream = archive.extractfile(member)
    if stream is None:
        raise IntakeError(f"无法读取 tar 成员：{member.name}")
    data = bytearray()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > maximum:
            raise IntakeError(f"tar 成员读取后超出预算：{member.name}")
    if len(data) != member.size:
        raise IntakeError(f"tar 成员长度不一致：{member.name}")
    return bytes(data)


def _stream_selected_tar(
    archive_path: Path, wanted: dict[str, list[dict[str, Any]]], maximum: int,
    handler: Callable[[dict[str, Any], bytes], None],
) -> tuple[set[str], list[dict[str, Any]]]:
    found: set[str] = set()
    errors: list[dict[str, Any]] = []
    try:
        archive = tarfile.open(archive_path, mode="r|gz")
    except (OSError, tarfile.TarError) as exc:
        raise IntakeError(f"无法打开 PDMX tar：{archive_path}: {exc}") from exc
    with archive:
        for member in archive:
            try:
                name = _safe_source_path(member.name)
            except IntakeError:
                continue
            if name not in wanted:
                continue
            if name in found:
                errors.append({"path": name, "reason": "duplicate tar member"})
                continue
            found.add(name)
            try:
                data = _read_tar_member_bytes(archive, member, maximum)
            except IntakeError as exc:
                errors.append({"path": name, "reason": str(exc)})
                continue
            for candidate in wanted[name]:
                handler(candidate, data)
    return found, errors


def _reference_validation(reference: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    length = _parse_float(reference.get("lengthMs"))
    notes = reference.get("notes")
    if length is None or not MIN_DURATION_MS <= length <= MAX_DURATION_MS:
        errors.append("parsed_duration_outside_90s_30m")
    if not isinstance(notes, list) or not MIN_NOTES <= len(notes) <= MAX_NOTES:
        errors.append("parsed_note_count_outside_budget")
    duration_kinds = _parse_int(reference.get("durationKinds"))
    if duration_kinds is not None and duration_kinds < 2:
        errors.append("no_meaningful_duration_variety")
    return errors


def _load_midi_candidates(rows: list[dict[str, str]], archive_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    wanted: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for row in rows:
        mid_path = _safe_source_path(row["mid"], suffix=".mid")
        wanted[mid_path].append({"row": row, "midPath": mid_path})
    for path, candidates in list(wanted.items()):
        if len(candidates) > 1:
            for candidate in candidates:
                rejected.append({"stage": "midi", "path": path, "reason": "duplicate CSV rows point to the same MIDI path"})
            wanted[path] = []

    parsed: list[dict[str, Any]] = []
    counters: collections.Counter[str] = collections.Counter()

    def handle(candidate: dict[str, Any], data: bytes) -> None:
        source_hash = sha256_bytes(data)
        try:
            reference = parse_smf(data)
            reference_errors = _reference_validation(reference)
            if reference_errors:
                raise IntakeError(", ".join(reference_errors))
        except (IntakeError, ValueError, KeyError, TypeError) as exc:
            rejected.append({"stage": "midi", "path": candidate["midPath"], "reason": str(exc)})
            counters["rejected_midi_parse_or_budget"] += 1
            return
        candidate.update({"data": data, "sourceSha256": source_hash, "reference": reference})
        parsed.append(candidate)
        counters["midi_members_parsed"] += 1

    found, tar_errors = _stream_selected_tar(archive_path, wanted, MAX_MIDI_BYTES, handle)
    for error in tar_errors:
        rejected.append({"stage": "midi", **error})
        counters["rejected_tar_member"] += 1
    for path, candidates in wanted.items():
        if path not in found:
            for candidate in candidates:
                rejected.append({"stage": "midi", "path": path, "reason": "MIDI member not found in complete tar"})
                counters["rejected_missing_midi_member"] += 1
    counters["midi_paths_wanted"] = len(wanted)
    counters["midi_paths_found"] = len(found)
    parsed.sort(key=lambda item: _ranking_key(item["row"]))
    unique: list[dict[str, Any]] = []
    source_hash_owner: dict[str, str] = {}
    for candidate in parsed:
        source_hash = candidate["sourceSha256"]
        if source_hash in source_hash_owner:
            rejected.append({"stage": "midi", "path": candidate["midPath"], "reason": "duplicate source MIDI SHA256", "duplicateOf": source_hash_owner[source_hash]})
            counters["rejected_duplicate_source_sha256"] += 1
            continue
        source_hash_owner[source_hash] = candidate["midPath"]
        unique.append(candidate)
    counters["midi_unique_source_hashes"] = len(unique)
    return unique, rejected, dict(counters)



def _metadata_fields(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    score = data.get("score") if isinstance(data.get("score"), dict) else {}
    return {
        "title": score.get("title"), "song_name": score.get("song_name"), "artist_name": score.get("artist_name"),
        "composer_name": score.get("composer_name"), "license": score.get("license"), "license_url": data.get("license_url"),
        "is_public_domain": data.get("is_public_domain", score.get("is_public_domain")), "duration": score.get("duration"),
        "instruments": score.get("instruments"), "url": score.get("url"), "user": score.get("user"),
        "score_id": score.get("id"), "publisher": score.get("publisher"), "parts": score.get("parts"), "parts_names": score.get("parts_names"),
    }


def _field_comparison(source_value: Any, metadata_value: Any) -> dict[str, Any]:
    if source_value is None or metadata_value is None:
        return {"status": "missing-on-one-side", "source": source_value, "metadata": metadata_value}
    if _is_missing(source_value) or _is_missing(metadata_value):
        return {"status": "source-na-preserved", "source": source_value, "metadata": metadata_value}
    if _raw(source_value) == _raw(metadata_value):
        status = "exact"
    elif _normalise_text(source_value) == _normalise_text(metadata_value):
        status = "normalized-equal"
    else:
        status = "different-source-fields"
    return {"status": status, "source": source_value, "metadata": metadata_value}


def _validate_metadata(row: dict[str, str], payload: Any, metadata_path: str) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        raise IntakeError("metadata JSON 顶层不是对象")
    data = payload.get("data")
    score = data.get("score") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(score, dict):
        raise IntakeError("metadata JSON 缺少 data.score 对象")
    fields = _metadata_fields(payload)
    errors: list[str] = []
    suspicious_fields = [name for name in ("title", "song_name", "artist_name", "composer_name") if _has_suspicious_text(fields.get(name))]
    if suspicious_fields:
        errors.append("metadata_suspicious_text_encoding:" + ",".join(suspicious_fields))
    metadata_signals = _modern_rights_signals({
        "title": fields.get("title"), "song_name": fields.get("song_name"), "artist_name": fields.get("artist_name"),
        "composer_name": fields.get("composer_name"), "genres": "", "tags": "",
    })
    if metadata_signals:
        errors.append("metadata_modern_or_popular_rights_signal:" + ",".join(metadata_signals))
    score_id = fields.get("score_id")
    path_stem = PurePosixPath(metadata_path).stem
    if score_id is not None and _raw(score_id).strip() and _raw(score_id).strip() != path_stem:
        errors.append("metadata_score_id_does_not_match_metadata_path")
    metadata_license = _raw(fields.get("license")).strip().casefold()
    if metadata_license and metadata_license not in {"publicdomain", "public domain"}:
        errors.append("metadata_license_not_publicdomain")
    metadata_public = _parse_bool(fields.get("is_public_domain"))
    csv_public = _parse_bool(row.get("is_public_domain")) if "is_public_domain" in row else None
    if metadata_public is not True:
        errors.append("metadata_is_public_domain_not_true")
    if csv_public is not None and csv_public != metadata_public:
        errors.append("csv_and_metadata_is_public_domain_differ")
    csv_url = _raw(row.get("license_url")).strip()
    metadata_url = _raw(fields.get("license_url")).strip()
    if csv_url and not _is_missing(csv_url) and metadata_url and not _is_missing(metadata_url) and csv_url != metadata_url:
        errors.append("csv_and_metadata_license_url_differ")
    score_url = _raw(fields.get("url")).strip()
    if not re.match(r"^https?://[^\s]+$", score_url, re.IGNORECASE):
        errors.append("metadata_score_url_missing_or_not_http")
    comparisons = {
        key: _field_comparison(row.get(key), fields.get(key))
        for key in ("title", "song_name", "artist_name", "composer_name", "license", "is_public_domain")
    }
    return {"fields": fields, "comparisons": comparisons, "validation": {"status": "PASS" if not errors else "REJECT", "errors": errors}}, errors


def _load_metadata_candidates(rows: list[dict[str, Any]], archive_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    wanted: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for candidate in rows:
        metadata_path = _safe_source_path(candidate["row"]["metadata"], suffix=".json")
        candidate["metadataPath"] = metadata_path
        wanted[metadata_path].append(candidate)
    parsed: list[dict[str, Any]] = []
    counters: collections.Counter[str] = collections.Counter()

    def handle(candidate: dict[str, Any], data: bytes) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
            summary, errors = _validate_metadata(candidate["row"], payload, candidate["metadataPath"])
            if errors:
                raise IntakeError(", ".join(errors))
        except (UnicodeDecodeError, json.JSONDecodeError, IntakeError, TypeError, KeyError) as exc:
            rejected.append({"stage": "metadata", "path": candidate["metadataPath"], "reason": str(exc)})
            counters["rejected_metadata_validation"] += 1
            return
        candidate.update({"metadataPayload": payload, "metadataSummary": summary})
        parsed.append(candidate)
        counters["metadata_members_validated"] += 1

    found, tar_errors = _stream_selected_tar(archive_path, wanted, MAX_METADATA_BYTES, handle)
    for error in tar_errors:
        rejected.append({"stage": "metadata", **error})
        counters["rejected_tar_member"] += 1
    for path, candidates in wanted.items():
        if path not in found:
            for candidate in candidates:
                rejected.append({"stage": "metadata", "path": path, "reason": "metadata member not found in complete tar"})
                counters["rejected_missing_metadata_member"] += 1
    counters["metadata_paths_wanted"] = len(wanted)
    counters["metadata_paths_found"] = len(found)
    parsed.sort(key=lambda item: _ranking_key(item["row"]))
    return parsed, rejected, dict(counters)


def _work_identity(row: dict[str, str]) -> dict[str, str]:
    source_title = row.get("song_name", "") if not _is_missing(row.get("song_name")) else row.get("title", "")
    source_creator = row.get("composer_name", "") if not _is_missing(row.get("composer_name")) else row.get("artist_name", "")
    title_key = _normalise_text(source_title) or _normalise_text(row.get("title")) or "unknown-title"
    creator_key = _normalise_text(source_creator) or "unknown-creator"
    work_id = f"pdmx-work:{_slug(source_title, 'unknown-title')}::{_slug(source_creator, 'unknown-creator')}"
    return {
        "workId": work_id,
        "workTitleBasis": _raw(source_title),
        "workCreatorBasis": _raw(source_creator),
        "canonicalTitle": title_key,
        "canonicalCreator": creator_key,
    }



def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    row = candidate["row"]
    metadata_summary = candidate["metadataSummary"]
    work = _work_identity(row)
    version_label, version_basis = _version_label(row, metadata_summary)
    stem = _asset_stem(candidate["midPath"])
    return {
        "work": work,
        "workId": work["workId"],
        "editionId": f"pdmx:{ZENODO_RECORD_ID}:{stem}",
        "versionLabel": version_label,
        "versionBasis": version_basis,
    }


def _filter_candidates_against_existing(
    candidates: list[dict[str, Any]],
    existing_index: dict[str, Any],
    rejected: list[dict[str, Any]],
    counters: collections.Counter[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply hard source/edition dedupe while retaining marked new editions."""
    counts = counters if counters is not None else collections.Counter()
    kept: list[dict[str, Any]] = []
    seen_source_hashes: set[str] = set()
    seen_edition_ids: set[str] = set()
    seen_work_ids: set[str] = set()
    existing_source_hashes = existing_index.get("sourceHashes", set())
    existing_edition_ids = existing_index.get("editionIds", set())
    existing_work_edition_ids = existing_index.get("workEditionIds", {})

    for candidate in candidates:
        identity = _candidate_identity(candidate)
        source_sha = _normalise_source_sha256(
            candidate.get("sourceSha256"), context=f"candidate {candidate.get('midPath', '<unknown>')}"
        )
        edition_id = identity["editionId"]
        work_id = identity["workId"]
        context = {
            "stage": "existing-intake",
            "path": candidate["midPath"],
            "sourceSha256": source_sha,
            "editionId": edition_id,
            "workId": work_id,
        }
        if source_sha in existing_source_hashes:
            rejected.append({**context, "reason": "source SHA256 already exists in prior intake"})
            counts["rejected_existing_source_sha256"] += 1
            continue
        if edition_id in existing_edition_ids:
            rejected.append({**context, "reason": "EditionId already exists in prior intake"})
            counts["rejected_existing_edition_id"] += 1
            continue
        if source_sha in seen_source_hashes:
            rejected.append({**context, "reason": "duplicate source SHA256 within current batch"})
            counts["rejected_duplicate_batch_source_sha256"] += 1
            continue
        if edition_id in seen_edition_ids:
            rejected.append({**context, "reason": "duplicate EditionId within current batch"})
            counts["rejected_duplicate_batch_edition_id"] += 1
            continue

        same_work_existing = work_id in existing_work_edition_ids
        same_work_in_batch = work_id in seen_work_ids
        existing_editions = sorted(existing_work_edition_ids.get(work_id, set()))
        if same_work_existing:
            counts["retained_same_work_new_edition"] += 1
        elif not same_work_in_batch:
            counts["new_work_ids"] += 1
        if same_work_in_batch:
            counts["retained_same_work_multiple_editions_in_batch"] += 1

        candidate["_identity"] = identity
        if same_work_existing or same_work_in_batch:
            candidate["batchDeduplication"] = {
                "policy": "WorkId is a soft grouping key; a new EditionId is retained",
                "sameWorkIdAlreadyInExisting": same_work_existing,
                "existingEditionIds": existing_editions,
                "sameWorkIdWithinBatch": same_work_in_batch,
            }
        seen_source_hashes.add(source_sha)
        seen_edition_ids.add(edition_id)
        seen_work_ids.add(work_id)
        kept.append(candidate)

    counts["candidates_after_existing_dedupe"] = len(kept)
    return kept


def _select_batch(candidates: list[dict[str, Any]], *, offset: int, limit: int) -> list[dict[str, Any]]:
    if offset < 0:
        raise IntakeError("offset must be a non-negative integer")
    if limit <= 0:
        raise IntakeError("limit must be a positive integer")
    selected = candidates[offset:offset + limit]
    if len(selected) < limit:
        raise IntakeError(
            f"only {len(selected)} candidates remain after dedupe and offset={offset}; need {limit}; output directory was not created"
        )
    return selected


def _version_label(row: dict[str, str], metadata_summary: dict[str, Any]) -> tuple[str, list[str]]:
    fields = metadata_summary.get("fields", {})
    score_id = _raw(fields.get("score_id")).strip() or PurePosixPath(_safe_source_path(row["metadata"], suffix=".json")).stem
    source_title = _raw(row.get("title"))
    song_name = _raw(row.get("song_name"))
    instruments = fields.get("instruments")
    names: list[str] = []
    if isinstance(instruments, list):
        for instrument in instruments:
            if isinstance(instrument, dict) and not _is_missing(instrument.get("name")):
                names.append(_raw(instrument.get("name")).strip())
            elif isinstance(instrument, str) and not _is_missing(instrument):
                names.append(instrument.strip())
    title_part = source_title if not _is_missing(source_title) else "source title unavailable"
    parts = [f"PDMX score {score_id}", f"source title: {title_part}"]
    if names:
        parts.append("source instruments: " + ", ".join(dict.fromkeys(names)))
    label = " / ".join(parts)
    # PopBatchTool manifest-v2 caps VersionLabel at 256 characters. The complete
    # source title remains in metadata/records and the report.
    if len(label) > 256:
        label = label[:253].rstrip() + "..."
    basis = ["metadata.score.id", "csv.title"]
    if names:
        basis.append("metadata.score.instruments")
    if not _is_missing(song_name) and _normalise_text(song_name) != _normalise_text(source_title):
        basis.append("csv.song_name-distinguishes-work-title")
    return label, basis


def _decorated_display_title(source_title: str, suffix: str) -> tuple[str, bool]:
    """Append a stable edition marker while preserving QinBan's title limit."""
    source_title = source_title.strip() or "Untitled"
    suffix = suffix.strip()
    full = f"{source_title} ({suffix})"
    if len(full) <= CORE_TITLE_LIMIT:
        return full, False
    available = CORE_TITLE_LIMIT - len(suffix) - 2
    if available <= 0:
        return _bounded_core_title(full)
    return source_title[:available].rstrip() + f" ({suffix})", True


def _disambiguate_duplicate_display_titles(items: list[dict[str, Any]]) -> None:
    """Make same-title editions distinguishable without changing source identity."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for item in items:
        groups[(_normalise_text(item.get("title")), _normalise_text(item.get("artist")))].append(item)

    for group in groups.values():
        if len(group) < 2:
            continue
        used: set[str] = set()
        for item in sorted(group, key=lambda value: (value.get("editionId", ""), value.get("id", ""))):
            label = _raw(item.get("versionLabel"))
            match = re.search(r"PDMX score\s+([^/]+)", label, flags=re.IGNORECASE)
            suffix = f"PDMX score {match.group(1).strip()}" if match else _raw(item.get("editionId"))[-12:]
            candidate, truncated = _decorated_display_title(
                _raw(item.get("title")), suffix
            )
            if candidate in used:
                candidate, truncated = _decorated_display_title(
                    _raw(item.get("title")), f"{suffix} / {_raw(item.get('editionId'))[-8:]}"
                )
            used.add(candidate)
            item["title"] = candidate
            metadata_document = item.get("_metadataDocument")
            if isinstance(metadata_document, dict):
                derived = metadata_document.setdefault("derived", {})
                derived["displayTitle"] = candidate
                derived["titleWasTruncated"] = truncated
                derived["displayTitleDisambiguation"] = {
                    "reason": "duplicate-title-and-artist",
                    "suffix": suffix,
                    "workIdUnchanged": True,
                    "editionIdUnchanged": True,
                }


def _record_file_map(record: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("files"), list):
        return {}
    return {str(item.get("key")): item for item in record["files"] if isinstance(item, dict) and item.get("key")}


def _source_archive_evidence(source_root: Path, record: Any, verify_hashes: bool) -> dict[str, Any]:
    source_dir = source_root / "source"
    record_files = _record_file_map(record)
    evidence: dict[str, Any] = {
        "verificationMode": "sha256+md5+size against local download reports and Zenodo record when available" if verify_hashes else "not-run",
        "files": {},
    }
    for filename, report_name, record_key in ARCHIVE_SPECS:
        path = source_dir / filename
        if not path.is_file():
            raise IntakeError(f"缺少 PDMX 完整来源文件：{path}")
        item: dict[str, Any] = {"path": str(path.resolve()), "file": filename, "size": path.stat().st_size}
        report_path = source_root / report_name
        if verify_hashes:
            if not report_path.is_file():
                raise IntakeError(f"缺少来源下载报告，无法完成完整性核验：{report_path}")
            report = _read_json(report_path)
            expected_size = report.get("remoteSize")
            expected_md5 = _raw(report.get("md5")).casefold()
            expected_sha256 = _raw(report.get("sha256")).casefold()
            actual_md5, actual_sha256, actual_size = _hash_file(path)
            if expected_size is not None and int(expected_size) != actual_size:
                raise IntakeError(f"来源文件大小不匹配：{filename}")
            if expected_md5 and expected_md5 != actual_md5.casefold():
                raise IntakeError(f"来源文件 MD5 不匹配：{filename}")
            if expected_sha256 and expected_sha256 != actual_sha256.casefold():
                raise IntakeError(f"来源文件 SHA256 不匹配：{filename}")
            item.update({"md5": actual_md5, "sha256": actual_sha256, "size": actual_size, "downloadReport": str(report_path.resolve())})
            record_entry = record_files.get(record_key)
            if isinstance(record_entry, dict):
                checksum = _raw(record_entry.get("checksum"))
                if checksum.startswith("md5:") and checksum[4:].casefold() != actual_md5.casefold():
                    raise IntakeError(f"本地文件与 Zenodo record MD5 不匹配：{filename}")
                if record_entry.get("size") is not None and int(record_entry["size"]) != actual_size:
                    raise IntakeError(f"本地文件与 Zenodo record size 不匹配：{filename}")
                item["zenodoRecordFile"] = record_entry
        else:
            item["status"] = "not-verified"
        evidence["files"][filename] = item
    return evidence


def _minimal_record(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        links = record.get("links") if isinstance(record.get("links"), dict) else {}
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        return {
            "id": record.get("id", ZENODO_RECORD_ID), "doi": record.get("doi", "10.5281/zenodo.15571083"),
            "title": record.get("title", DATASET_TITLE), "recordUrl": links.get("self_html", ZENODO_RECORD_URL),
            "apiUrl": links.get("self", ZENODO_API_URL), "license": metadata.get("license", record.get("license")),
            "publicationDate": metadata.get("publication_date"),
        }
    return {"id": ZENODO_RECORD_ID, "doi": "10.5281/zenodo.15571083", "title": DATASET_TITLE, "recordUrl": ZENODO_RECORD_URL, "apiUrl": ZENODO_API_URL}




def _build_item(candidate: dict[str, Any], output: Path, retrieved_at: str) -> dict[str, Any]:
    row = candidate["row"]
    stem = _asset_stem(candidate["midPath"])
    metadata_summary = candidate["metadataSummary"]
    source_title = _raw(row.get("title")).strip()
    display_title, title_was_truncated = _bounded_core_title(source_title)
    metadata_fields = metadata_summary["fields"]
    identity = candidate.get("_identity") or _candidate_identity(candidate)
    work = identity["work"]
    version_label = identity["versionLabel"]
    version_basis = identity["versionBasis"]
    edition_id = identity["editionId"]
    item_id = f"pdmx-{stem}"
    midi_path = output / "midi" / f"{stem}.mid"
    reference_path = output / "references" / f"{stem}.json"
    metadata_record_path = output / "metadata" / "records" / f"{stem}.json"
    reference = dict(candidate["reference"])
    parsed_length_ms = _parse_float(reference.get("lengthMs"))
    source_duration_seconds = _parse_float(row.get("song_length.seconds"))
    timing = {
        "sourceCsvDurationSecondsRaw": _raw(row.get("song_length.seconds")),
        "sourceCsvDurationSeconds": source_duration_seconds,
        "parsedLengthMs": parsed_length_ms,
        "parsedDurationSeconds": parsed_length_ms / 1000 if parsed_length_ms is not None else None,
        "differenceSeconds": (parsed_length_ms / 1000 - source_duration_seconds) if parsed_length_ms is not None and source_duration_seconds is not None else None,
        "comparisonStatus": "source-field-preserved; parser-derived timing is not a music-accuracy approval",
    }
    reference.update({
        "schemaVersion": "pdmx-independent-smf-reference-v1",
        "sourcePath": f"./{candidate['midPath']}",
        "sourceSha256": candidate["sourceSha256"],
        "timingComparison": timing,
        "parserScope": "independent Python SMF parser; no audio inference, transcription, or game validation",
    })
    metadata_document = {
        "schemaVersion": "pdmx-source-record-v1",
        "retrievedAtUtc": retrieved_at,
        "provider": "PDMX",
        "zenodoRecordId": ZENODO_RECORD_ID,
        "qualification": {
            "status": "STRUCTURAL_CANDIDATE_ONLY",
            "qualityGrade": "ungraded",
            "rightsReview": "required",
            "musicReview": "required",
            "gameReview": "required",
            "redistributionVerified": False,
        },
        "source": {
            "dataPath": _raw(row.get("path")), "midPath": _raw(row.get("mid")), "metadataPath": _raw(row.get("metadata")),
            "sourceSha256": candidate["sourceSha256"], "csvRowSha256": _canonical_json_hash(row),
        },
        "csvRow": row,
        "metadataJson": candidate["metadataPayload"],
        "derived": {
            "work": work, "editionId": edition_id, "versionLabel": version_label, "versionBasis": version_basis,
            "metadataSummary": metadata_summary,
            "displayTitle": display_title, "sourceTitle": source_title,
            "titleWasTruncated": title_was_truncated,
            "rights": {
                "sourcePublicDomainFlag": _parse_bool(metadata_fields.get("is_public_domain")), "csvPublicDomainRaw": _raw(row.get("is_public_domain")), "sourceLicense": _raw(row.get("license")),
                "sourceLicenseUrl": _raw(row.get("license_url")), "redistributionVerified": False,
                "publicationStatus": "blocked-pending-manual-rights-review", "modernWorkAutoPublication": False,
                "note": "PDMX source flags and dataset license do not by themselves clear the underlying work or permit public redistribution.",
            },
            "outputPaths": {"midi": str(midi_path.resolve()), "reference": str(reference_path.resolve()), "metadataRecord": str(metadata_record_path.resolve())},
        },
    }
    batch_deduplication = candidate.get("batchDeduplication")
    if batch_deduplication:
        metadata_document["derived"]["batchDeduplication"] = batch_deduplication

    source_fields = {
        "title": _raw(row.get("title")), "song_name": _raw(row.get("song_name")), "artist_name": _raw(row.get("artist_name")),
        "composer_name": _raw(row.get("composer_name")), "license": _raw(row.get("license")), "license_url": _raw(row.get("license_url")),
        "is_public_domain": metadata_fields.get("is_public_domain"), "csv_is_public_domain": _raw(row.get("is_public_domain")), "duration": metadata_fields.get("duration"),
        "instruments": metadata_fields.get("instruments"), "url": metadata_fields.get("url"), "user": metadata_fields.get("user"),
    }
    item = {
        "id": item_id, "title": display_title, "songName": _raw(row.get("song_name")), "artist": _raw(row.get("artist_name")),
        "composer": _raw(row.get("composer_name")), "workId": work["workId"], "editionId": edition_id, "versionLabel": version_label,
        "versionBasis": version_basis, "sourceFields": source_fields, "sourceCsvRowSha256": _canonical_json_hash(row),
        "sourcePath": _raw(row.get("path")), "sourceMidiPath": _raw(row.get("mid")), "sourceMetadataPath": _raw(row.get("metadata")),
        "sourceSha256": candidate["sourceSha256"], "midiPath": str(midi_path.resolve()), "referencePath": str(reference_path.resolve()),
        "metadataRecordPath": str(metadata_record_path.resolve()), "sourceUrl": metadata_fields.get("url"), "metadataSource": ZENODO_RECORD_URL,
        "languageTags": [], "languageStatus": "not-stated-by-source", "durationMs": parsed_length_ms,
        "sourceDurationSeconds": source_duration_seconds, "notes": len(reference.get("notes", [])), "tempoChanges": reference.get("tempoChanges"),
        "durationKinds": reference.get("durationKinds"), "completeness": "source-all_valid", "musicReview": "not-reviewed", "gameReview": "not-tested",
        "redistributionVerified": False, "publicationStatus": "blocked-pending-manual-rights-review", "modernWorkAutoPublication": False,
        "rightsStatus": "candidate-unverified", "rightsNote": "Source public-domain fields are preserved but are not treated as public-redistribution clearance.",
        "referenceSchema": "pdmx-independent-smf-reference-v1", "intakeRetrievedAtUtc": retrieved_at,
        "_reference": reference, "_metadataDocument": metadata_document,
    }
    if batch_deduplication:
        item["batchDeduplication"] = batch_deduplication
    return item



def _contract_song(item: dict[str, Any]) -> dict[str, Any]:
    """Only fields declared by PopBatchTool Contracts.cs ManifestSong."""
    return {
        "Id": item["id"], "Title": item["title"], "Artist": item["artist"], "MidiPath": item["midiPath"],
        "ReferencePath": item["referencePath"], "SourceUrl": item["sourceUrl"], "SourceSha256": item["sourceSha256"],
        "LanguageTags": item["languageTags"], "Artists": [item["artist"]], "Provider": "PDMX", "SourceCommit": SOURCE_COMMIT,
        "SourceRecord": ZENODO_RECORD_URL, "BatchKind": BATCH_KIND, "Author": "PDMX dataset authors", "Category": "pdmx-candidate",
        "Description": "PDMX structural candidate; rights, music, and game review pending", "IdPattern": "pdmx-<source-CID>",
        "SmartInterludes": True, "WorkId": item["workId"], "EditionId": item["editionId"], "VersionLabel": item["versionLabel"],
        "License": item["sourceFields"]["license"] or "publicdomain", "LicenseUrl": _http_url_or_empty(item["sourceFields"]["license_url"]),
        "RightsStatus": "candidate-unverified", "RightsNote": item["rightsNote"], "Album": "", "Aliases": [], "Tags": [],
        "Completeness": "source-all_valid", "MusicReview": "not-reviewed", "GameReview": "not-tested", "RedistributionVerified": False,
    }


def _contract_manifest(songs: list[dict[str, Any]], retrieved_at: str) -> dict[str, Any]:
    """Top-level fields are intentionally limited to Manifest in Contracts.cs."""
    return {
        "Songs": [_contract_song(item) for item in songs], "SourceCommit": SOURCE_COMMIT, "SourceRecord": ZENODO_RECORD_URL,
        "RetrievedAtUtc": retrieved_at, "Provider": "PDMX", "BatchKind": BATCH_KIND, "SourceUrl": ZENODO_RECORD_URL,
        "License": "CC-BY-4.0-dataset-record-metadata", "LicenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "RightsStatus": "candidate-unverified", "RightsNote": "Candidate intake only; underlying work redistribution is unverified and requires manual rights review.",
        "RedistributionVerified": False, "Author": "PDMX dataset authors", "Category": "pdmx-candidate", "Description": "Metadata-first structural candidate batch; not an A-grade or publishable library.",
        "IdPattern": "pdmx-<source-CID>", "SmartInterludesDefault": True,
    }


def _source_license_text(record: Any) -> str:
    minimal = _minimal_record(record)
    license_value = minimal.get("license")
    if isinstance(license_value, dict):
        license_id = license_value.get("id") or license_value.get("title") or "cc-by-4.0"
    else:
        license_id = license_value or "cc-by-4.0"
    return f"""PDMX source attribution and rights notice
==========================================

Dataset: {DATASET_TITLE}
Zenodo record: {ZENODO_RECORD_URL}
DOI: 10.5281/zenodo.15571083
Dataset-record license metadata: {license_id}
Creative Commons reference: https://creativecommons.org/licenses/by/4.0/

This file documents the dataset record used for this local metadata-first intake.
The record-level CC BY 4.0 metadata is not a blanket relicensing or public-release
permission for every underlying score, composition, recording, or arrangement. The
PDMX record warns about public-facing versus internal license discrepancies; this
intake uses the no_license_conflict subset, preserves source fields verbatim, and
sets redistributionVerified=false for every selected item.

No selected item is approved for public redistribution or commercial distribution
by this intake. Modern or popular-work signals are filtered into the rights-review
queue, and the remaining selected items are also not automatically cleared. Any
later bundling, publication, or distribution requires a separate rights review
bound to the exact source file hash, work, edition, and intended use.

Required attribution for the dataset record should include the PDMX authors and
record/paper citation described by the source record. This notice does not replace
the source record, its terms, or a work-specific rights decision.
"""

def _readme_text(output: Path, source_root: Path, selected: list[dict[str, Any]], counters: dict[str, int], archive_evidence: dict[str, Any], retrieved_at: str) -> str:
    work_count = len({item["workId"] for item in selected})
    verified_files = sum(1 for value in archive_evidence.get("files", {}).values() if value.get("sha256"))
    return f"""# PDMX metadata-first batch intake（100 条候选）

- 状态：`PASS_PDMX_METADATA_FIRST_BATCH`
- 生成时间（UTC）：`{retrieved_at}`
- 输出目录：`{output.resolve()}`
- 本地来源根目录：`{source_root.resolve()}`
- Zenodo record：[{ZENODO_RECORD_URL}]({ZENODO_RECORD_URL})
- 选中条目：`{len(selected)}`
- 选中条目对应的不同 WorkId：`{work_count}`
- 已核验完整来源文件：`{verified_files}/4`

## 做了什么

1. 读取 `source/PDMX.complete.csv` 和 `source/subset_paths/no_license_conflict.txt`。
2. 只保留 `license=publicdomain`、`is_public_domain=True`、`license_conflict=False`、`subset:rated_deduplicated=True`、`subset:all_valid=True`、`is_best_unique_arrangement=True` 的行。
3. 过滤 90 秒至 30 分钟、100 至 100,000 个源元数据音符、非空标题和非空艺术家。作曲者、song_name、乐器、user 等字段缺失时保留原值，不猜 `NA`。
4. 过滤明显编码乱码和疑似现代/流行作品信号；这些行逐条保留在 `acquisition-report.json` 的 reject/review queue。
5. 按评分、收藏数、评分人数、浏览数、标题、艺术家、作曲者、源 path 进行确定性排序。
6. 以 `tarfile` 的流式 `r|gz` 模式读取完整 `mid` 和 `metadata` tar；没有整包解压，也没有从音频或歌名生成音符。
7. 使用 `tools/smf_reference.py` 做独立 SMF 解析，记录起音、时值、速度变化、音符数和时长；解析通过不等于人工听辨或游戏验收。

## 准入状态与审核队列

`manifest.json` 和 `build-manifest.json` 遵循当前 `tools/PopBatchTool/Contracts.cs` 的 v2 允许字段，便于后续离线工具读取；它们**不携带额外 PDMX 原始字段**。原始 CSV 行、完整 metadata JSON、composer、song_name、duration、instruments、url、user、资格证据和派生 Work/Edition/Version 信息全部在 `metadata/records/*.json` 与 `acquisition-report.json` 中。

本目录是**结构化候选 intake**，不是 A 级审核结果，也不是可发布曲库。每条选中记录均有：

- `RedistributionVerified=false`
- `RightsStatus=candidate-unverified`
- `MusicReview=not-reviewed`
- `GameReview=not-tested`
- `admissionStatus=STRUCTURAL_CANDIDATE_ONLY`（位于报告/记录，不放入合同 song 对象）
- `qualityGrade=ungraded`

疑似乱码、CSV/metadata 权利冲突、`metadata.is_public_domain=false`、明显现代/流行信号等拒绝项逐条保留；没有把 publicdomain/no_license_conflict 自动等同可公开分发。

## 输出文件

- `manifest.json`：仅包含 PopBatchTool Contracts.cs 当前允许的 v2 字段。
- `build-manifest.json`：同样只包含 v2 合同字段；本轮没有运行转换器，也没有写入产品曲库。
- `midi/`：100 个真实提取的 MIDI，文件名由 PDMX source path 的稳定 CID 派生。
- `references/`：独立 SMF 解析结果和源时序对照字段。
- `metadata/records/`：每条记录的原始 CSV 行、原始 metadata JSON 和派生 Work/Edition/Version 证据。
- `acquisition-report.json`：筛选、逐条拒绝、哈希、解析统计和审核队列。
- `version-groups.json`：同一 WorkId 下多个 EditionId 的关系；每个版本都有明确的 VersionLabel。
- `source-archive-evidence.json`：PDMX 完整文件的大小、MD5、SHA256 和本地下载报告证据。
- `zenodo-record-15571083.json`：本地保存的 Zenodo record 原始 JSON。
- `source-LICENSE.txt`：来源归属和权利边界说明。

## WorkId、EditionId、VersionLabel

- `WorkId` 使用来源 `song_name`（缺失时才使用来源 `title`）和 `composer_name`（缺失时才使用 `artist_name`）的规范化键。没有把 `NA` 猜成真实名称。
- `EditionId` 使用 Zenodo record 与稳定 source CID；不同 MIDI source path 即使 WorkId 相同，也保留独立 EditionId。
- `VersionLabel` 记录具体 MuseScore score id、CSV source title 和 metadata instruments；它描述来源证据，不宣称原版、翻唱版或平台录音身份。

## 权利与未完成边界

- 所有条目均保持 `RedistributionVerified=false`、`RightsStatus=candidate-unverified`，不可直接作为可公开发布或商业分发素材。
- PDMX 的 public-domain 字段和数据集记录许可没有自动清除底层作品、编配或现代作品；现代/流行信号已过滤进审核队列。
- `MusicReview=not-reviewed`、`GameReview=not-tested`；本轮没有进行人工听辨、原神内演奏、按键、提权、进程注入、内存读取或 EXE/UserData 修改。
- 本轮也没有写入 `Songs`、`dist` 或任何运行时目录。

## 复现命令

```powershell
python tools\\acquire_pdmx_batch.py catalog-intake\\pdmx-2026-10-06\\batch-100-2026-10-06
```

命令要求输出目录不存在，防止覆盖既有证据。源下载报告和哈希核验默认开启；若只是对独立测试夹具运行，应显式使用测试代码的 `verify_archive_hashes=False`，不要把测试夹具结果当真实来源证据。
"""


def _write_output(
    output: Path,
    source_root: Path,
    record: Any,
    selected_candidates: list[dict[str, Any]],
    selection_counters: dict[str, int],
    rejected: list[dict[str, Any]],
    archive_evidence: dict[str, Any],
    subset_evidence: dict[str, Any],
    retrieved_at: str,
    existing_manifest_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=False)
    (output / "midi").mkdir()
    (output / "references").mkdir()
    (output / "metadata" / "records").mkdir(parents=True)

    pending_items: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        pending_items.append(_build_item(candidate, output, retrieved_at))
    _disambiguate_duplicate_display_titles(pending_items)

    items: list[dict[str, Any]] = []
    for item in pending_items:
        candidate = next(candidate for candidate in selected_candidates if candidate["sourceSha256"] == item["sourceSha256"])
        reference = item.pop("_reference")
        metadata_document = item.pop("_metadataDocument")
        _write_bytes_new(Path(item["midiPath"]), candidate["data"])
        _write_json_new(Path(item["referencePath"]), reference)
        _write_json_new(Path(item["metadataRecordPath"]), metadata_document)
        items.append(item)

    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in items:
        groups[item["workId"]].append({
            "id": item["id"], "title": item["title"], "songName": item["songName"], "artist": item["artist"],
            "composer": item["composer"], "editionId": item["editionId"], "versionLabel": item["versionLabel"],
            "sourcePath": item["sourcePath"], "metadataRecordPath": item["metadataRecordPath"],
        })
    _write_json_new(output / "version-groups.json", {
        "policy": "same WorkId may contain multiple source editions; EditionId and VersionLabel remain distinct and source-based",
        "groups": dict(sorted(groups.items())),
    })
    _write_json_new(output / "source-archive-evidence.json", archive_evidence)
    _write_json_new(output / f"zenodo-record-{ZENODO_RECORD_ID}.json", record if isinstance(record, dict) else _minimal_record(record))
    _write_text_new(output / "source-LICENSE.txt", _source_license_text(record))

    manifest = _contract_manifest(items, retrieved_at)
    # Both names are intentionally contract-compatible. No extra PDMX fields are
    # inserted into Manifest/ManifestSong because Contracts.cs rejects unknown JSON.
    _write_json_new(output / "manifest.json", manifest)
    _write_json_new(output / "build-manifest.json", manifest)

    report = {
        "status": "PASS_PDMX_METADATA_FIRST_BATCH",
        "admissionStatus": "STRUCTURAL_CANDIDATE_ONLY",
        "qualityGrade": "ungraded",
        "eligibleForProductInstall": False,
        "rightsReviewQueue": "required",
        "musicReviewQueue": "required",
        "gameReviewQueue": "required",
        "provider": "PDMX",
        "batchKind": BATCH_KIND,
        "sourceCommit": SOURCE_COMMIT,
        "zenodoRecordId": ZENODO_RECORD_ID,
        "selectedCount": len(items),
        "distinctWorkIds": len({item["workId"] for item in items}),
        "sourceHashes": len({item["sourceSha256"] for item in items}),
        "sourceArchiveEvidence": archive_evidence,
        "existingIntake": existing_manifest_summary or _existing_manifest_summary(_empty_existing_manifest_index()),
        "selectionCounters": selection_counters,
        "rejectedCount": len(rejected),
        "rejected": rejected,
        "selected": [
            {
                "id": item["id"], "title": item["title"], "songName": item["songName"], "artist": item["artist"], "composer": item["composer"],
                "workId": item["workId"], "editionId": item["editionId"], "versionLabel": item["versionLabel"],
                "sourcePath": item["sourcePath"], "sourceSha256": item["sourceSha256"],
                "metadataRecordPath": item["metadataRecordPath"], "admissionStatus": "structural-candidate-only", "qualityGrade": "ungraded",
                "rightsReview": "required", "musicReview": "not-reviewed", "gameReview": "not-tested",
            }
            for item in items
        ],
        "limitations": [
            "PDMX source public-domain flags and dataset-record license do not clear underlying works or permit public redistribution.",
            "No modern work was auto-approved; every item remains blocked for manual rights review.",
            "SMF parsing is structural/timing evidence only, not human music review or original-audio matching.",
            "No normalized QinBan score, instrument adaptation, runtime installation, EXE change, UserData change, or game input was performed.",
        ],
    }
    _write_json_new(output / "acquisition-report.json", report)
    _write_text_new(output / "README.md", _readme_text(output, source_root, items, selection_counters, archive_evidence, retrieved_at))
    return {"manifest": manifest, "buildManifest": manifest, "report": report}


def acquire_batch(
    source_root: Path,
    output: Path,
    *,
    limit: int = 100,
    offset: int = 0,
    exclude_manifests: Iterable[Path | str] | Path | str | None = None,
    record_json: Path | None = None,
    verify_archive_hashes: bool = True,
    enforce_output_root: bool = True,
    now_fn: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Build one new PDMX evidence directory without touching product data."""
    source_root = source_root.resolve()
    output = output.resolve()
    if limit <= 0:
        raise IntakeError("limit 必须为正整数")
    if offset < 0:
        raise IntakeError("offset must be non-negative")
    if not source_root.is_dir():
        raise IntakeError(f"PDMX source root 不存在：{source_root}")
    if output.exists():
        raise IntakeError(f"输出目录已存在，拒绝覆盖：{output}")
    intake_root = (ROOT / "catalog-intake").resolve()
    if enforce_output_root and not output.is_relative_to(intake_root):
        raise IntakeError(f"生产运行必须把输出写入 catalog-intake 内：{output}")
    if output == source_root:
        raise IntakeError("输出目录不能等于 PDMX source root")

    record: Any = {}
    if record_json is not None and record_json.is_file():
        record = _read_json(record_json)
    elif verify_archive_hashes and record_json is not None:
        raise IntakeError(f"缺少 Zenodo record JSON：{record_json}")

    archive_evidence = _source_archive_evidence(source_root, record, verify_archive_hashes)
    subset_paths, subset_evidence = _load_subset_paths(source_root)
    rows, selection_counters, rejected = _load_candidate_rows(source_root, subset_paths)
    if len(rows) < limit:
        raise IntakeError(f"保守 metadata 筛选后只有 {len(rows)} 条候选，少于目标 {limit} 条")

    midi_candidates, midi_rejected, midi_counters = _load_midi_candidates(rows, source_root / "source" / "mid.complete.tar.gz")
    rejected.extend(midi_rejected)
    selection_counters.update(midi_counters)
    if not midi_candidates:
        raise IntakeError("完整 mid tar 中没有通过独立 SMF 解析的候选")

    metadata_candidates, metadata_rejected, metadata_counters = _load_metadata_candidates(
        midi_candidates, source_root / "source" / "metadata.complete.tar.gz"
    )
    rejected.extend(metadata_rejected)
    selection_counters.update(metadata_counters)
    metadata_candidates.sort(key=lambda item: _ranking_key(item["row"]))
    existing_index = _load_existing_manifest_index(exclude_manifests)
    dedupe_counters: collections.Counter[str] = collections.Counter()
    deduped_candidates = _filter_candidates_against_existing(
        metadata_candidates, existing_index, rejected, dedupe_counters
    )
    selection_counters.update(dedupe_counters)
    selection_counters["selection_offset"] = offset
    selection_counters["existing_manifest_count"] = existing_index["manifestCount"]
    selection_counters["existing_manifest_song_count"] = existing_index["songCount"]
    selection_counters["existing_unique_work_ids"] = len(existing_index["workIds"])
    selection_counters["metadata_valid_candidates_after_existing_dedupe"] = len(deduped_candidates)
    selected = _select_batch(deduped_candidates, offset=offset, limit=limit)
    selection_counters["selected_count"] = len(selected)
    selection_counters["eligible_metadata_rows"] = len(rows)
    selection_counters["metadata_valid_candidates"] = len(metadata_candidates)
    return _write_output(
        output, source_root, record, selected, selection_counters, rejected,
        archive_evidence, subset_evidence, now_fn(),
        existing_manifest_summary=_existing_manifest_summary(existing_index),
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="新建的 intake 输出目录，必须位于 catalog-intake 内")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT, help="PDMX 本地 intake 根目录")
    parser.add_argument("--record-json", type=Path, default=DEFAULT_RECORD_JSON, help="本地 Zenodo record JSON")
    parser.add_argument("--limit", type=int, default=100, help="batch size; default 100")
    parser.add_argument("--offset", type=int, default=0, help="skip this many candidates after deterministic dedupe")
    parser.add_argument(
        "--exclude-manifest", action="append", default=[],
        help="repeat an existing intake directory or manifest.json; hard-dedupe SourceSha256/EditionId",
    )
    parser.add_argument("--skip-archive-hash", action="store_true", help="isolated tests only; not source-integrity evidence")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = acquire_batch(
            args.source_root, args.output, limit=args.limit, offset=args.offset,
            exclude_manifests=args.exclude_manifest, record_json=args.record_json,
            verify_archive_hashes=not args.skip_archive_hash,
        )
    except (IntakeError, OSError, tarfile.TarError, ValueError) as exc:
        print(f"FAIL PDMX intake: {exc}", flush=True)
        return 2
    report = result["report"]
    print(
        f"PASS PDMX intake: selected={report['selectedCount']} workIds={report['distinctWorkIds']} "
        f"rejected={report['rejectedCount']} output={args.output.resolve()}", flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())






