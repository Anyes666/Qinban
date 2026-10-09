"""Independent, reusable POP909/structured-score batch validator.

This tool is read-only for intake, stage, baseline, and referenced files. It
writes only the new report named by --report. Counts come from the supplied
baseline catalogue and manifest.json; no POP909-specific 200/332 constants.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

sys.dont_write_bytecode = True
try:
    from smf_reference import parse_smf
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from smf_reference import parse_smf

TIMING_TOLERANCE_MS = 0.0021
NOTE_FIELDS = {"pitch", "startMs", "durationMs", "track", "velocity", "percussion"}
VERSION_FIELDS = ("versionLabel", "editionId", "workId", "provider", "sourceUrl")
REVIEW_NOT_REVIEWED = {"not-reviewed", "unreviewed", "not_reviewed"}
GAME_NOT_TESTED = {"not-tested", "untested", "not_tested"}


class AuditError(ValueError):
    """A violation independently observed by this validator."""


def require(value, message):
    if not value:
        raise AuditError(message)


def manifest_value(mapping, *names, default=None):
    """Read the v1 lowercase intake contract and the PopBatchTool v2 PascalCase contract."""
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def normalize_manifest_song(raw):
    require(isinstance(raw, dict), "manifest song must be an object")
    aliases = {
        "id": ("id", "Id"),
        "sourceSha256": ("sourceSha256", "SourceSha256"),
        "editionId": ("editionId", "EditionId"),
        "workId": ("workId", "WorkId"),
        "versionLabel": ("versionLabel", "VersionLabel"),
        "provider": ("provider", "Provider"),
        "sourceUrl": ("sourceUrl", "SourceUrl"),
        "midiPath": ("midiPath", "MidiPath"),
        "referencePath": ("referencePath", "ReferencePath"),
        "sourcePath": ("sourcePath", "SourcePath"),
    }
    result = {}
    for canonical, names in aliases.items():
        value = manifest_value(raw, *names, default=None)
        if value is not None:
            result[canonical] = value
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hash_value(value, label: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value),
            f"{label}: expected SHA-256 hex")
    return value.upper()


def no_links(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        attrs = getattr(info, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        require(not stat.S_ISLNK(info.st_mode) and not attrs & reparse,
                f"Symlink/reparse point refused: {part}")
    return path


def strict_json(path: Path):
    label = str(path)
    def pairs(items):
        result, seen = {}, set()
        for key, value in items:
            folded = key.casefold()
            require(folded not in seen, f"{label}: duplicate JSON property {key}")
            seen.add(folded)
            result[key] = value
        return result
    def constant(value):
        raise AuditError(f"{label}: non-finite JSON number {value}")
    try:
        text = no_links(path).read_text(encoding="utf-8-sig")
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditError(f"{label}: invalid JSON: {error}") from error


def same(actual, expected) -> bool:
    """JSON equality without Python's True == 1 equivalence."""
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and actual.keys() == expected.keys()
                and all(same(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(same(a, b) for a, b in zip(actual, expected)))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


def number(value, label, low=0.0, high=1_800_000.0):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            f"{label}: invalid finite number")
    return value


def validate_notes(document, label):
    require(isinstance(document, dict) and isinstance(document.get("notes"), list)
            and 0 < len(document["notes"]) <= 100_000, f"{label}: invalid notes")
    for index, note in enumerate(document["notes"]):
        where = f"{label} note {index}"
        require(isinstance(note, dict) and set(note) == NOTE_FIELDS,
                f"{where}: note fields must be exactly {sorted(NOTE_FIELDS)}")
        require(type(note["pitch"]) is int and 0 <= note["pitch"] <= 127, f"{where}: pitch")
        require(type(note["track"]) is int and 0 <= note["track"] <= 255, f"{where}: track")
        require(type(note["velocity"]) is int and 1 <= note["velocity"] <= 127, f"{where}: velocity")
        require(type(note["percussion"]) is bool, f"{where}: percussion")
        number(note["startMs"], f"{where}: startMs")
        number(note["durationMs"], f"{where}: durationMs", 1e-12, 60_000)
        require(note["startMs"] + note["durationMs"] <= 1_800_000,
                f"{where}: note end out of budget")
    number(document.get("lengthMs"), f"{label}: lengthMs")
    number(document.get("bpm"), f"{label}: bpm", 1e-12, 1_000_000_000)
    return sorted(document["notes"], key=lambda n: (
        n["track"], n["pitch"], n["velocity"], n["percussion"],
        n["startMs"], n["durationMs"]))


def compare_timing(actual, expected, label):
    actual_notes = validate_notes(actual, label)
    expected_notes = validate_notes(expected, label + " reference")
    require(len(actual_notes) == len(expected_notes), f"{label}: note count differs")
    max_onset = max_duration = 0.0
    for index, (a, b) in enumerate(zip(actual_notes, expected_notes)):
        for field in ("pitch", "track", "velocity", "percussion"):
            require(a[field] == b[field], f"{label}: {field} differs at note {index}")
        max_onset = max(max_onset, abs(a["startMs"] - b["startMs"]))
        max_duration = max(max_duration, abs(a["durationMs"] - b["durationMs"]))
    max_length = abs(actual["lengthMs"] - expected["lengthMs"])
    require(max(max_onset, max_duration, max_length) <= TIMING_TOLERANCE_MS,
            f"{label}: timing differs (onset={max_onset:.12g}, duration={max_duration:.12g}, length={max_length:.12g} ms)")
    bpm_error = abs(actual["bpm"] - expected["bpm"])
    require(bpm_error <= max(1e-6, expected["bpm"] * 1e-8), f"{label}: BPM differs")
    return {"notes": len(actual_notes), "maxOnsetErrorMs": max_onset,
            "maxDurationErrorMs": max_duration, "maxLengthErrorMs": max_length,
            "bpmError": bpm_error}


def canonical_defaults(entry, *, expected_smart_interludes=None):
    result = copy.deepcopy(entry)
    options = result.get("options")
    require(isinstance(options, dict), f"{entry.get('id', '<entry>')}: options missing")
    options.setdefault("smartInterludes", None)
    actual = options["smartInterludes"]
    if expected_smart_interludes is None:
        require(actual is None,
                f"{entry.get('id', '<entry>')}: SmartInterludes must inherit null")
    else:
        require(actual is None or actual == expected_smart_interludes,
                f"{entry.get('id', '<entry>')}: SmartInterludes disagrees with declared default")
    return result


def canonical_existing_defaults(entry):
    """Canonicalize an existing entry without imposing a new-entry default.

    A catalogue may already contain an explicitly enabled SmartInterludes
    value from an earlier, validated batch.  The baseline contract is that the
    value is preserved byte-for-byte in metadata, not that every historical
    entry must inherit null.  New entries continue to use canonical_defaults()
    and therefore remain subject to the declared batch default.
    """
    result = copy.deepcopy(entry)
    require(isinstance(result.get("options"), dict),
            f"{entry.get('id', '<entry>')}: options missing")
    return result


def relative_path(value, label):
    require(isinstance(value, str) and value, f"{label}: empty relative path")
    value = value.replace("\\", "/")
    pieces = value.split("/")
    require(not value.startswith("/") and all(piece not in ("", ".", "..") for piece in pieces)
            and not any(":" in piece or piece.endswith((" ", ".")) for piece in pieces),
            f"{label}: unsafe relative path {value}")
    return value


def resolve_manifest_path(intake: Path, manifest_dir: Path, value, label) -> Path:
    require(isinstance(value, str) and value, f"{label}: missing path")
    path = Path(value)
    if not path.is_absolute():
        candidates = (manifest_dir / path, intake / path)
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    path = no_links(path)
    require(path.is_file(), f"{label}: missing file {path}")
    return path

def catalog_rows(path: Path):
    path = no_links(path)
    require(path.is_file(), f"Missing catalogue: {path}")
    for suffix in ("-wal", "-shm", "-journal"):
        require(not path.with_name(path.name + suffix).exists(), f"SQLite sidecar refused: {suffix}")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                    "SQLite integrity check failed")
            require(not db.execute("PRAGMA foreign_key_check").fetchall(), "SQLite foreign key check failed")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require({"meta", "entries", "search_index"} <= tables, "Catalogue tables incomplete")
            meta = dict(db.execute("SELECT key,value FROM meta"))
            require(meta.get("synthetic", "0") in {"0", "false", "False"},
                    "Catalogue synthetic marker is not false")
            entries = db.execute("SELECT id,work_id,relative_path,content_hash,original_hash,metadata_json FROM entries ORDER BY id").fetchall()
            columns = [row[1] for row in db.execute("PRAGMA table_info(search_index)")]
            search = db.execute("SELECT * FROM search_index ORDER BY entry_id").fetchall()
            return meta, columns, entries, search
    except sqlite3.Error as error:
        raise AuditError(f"Invalid/read-failed catalogue {path}: {error}") from error


def parse_entries(rows, label):
    result, paths, editions = {}, set(), set()
    for identity, work_id, relative, content_hash, original_hash, raw in rows:
        require(isinstance(identity, str) and identity and identity not in result,
                f"{label}: duplicate/empty stable ID")
        relative = relative_path(relative, f"{label} {identity}")
        require(relative.casefold() not in paths and relative.lower().endswith(".json"),
                f"{label}: duplicate/non-JSON entry path {relative}")
        try:
            entry = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise AuditError(f"{label} {identity}: invalid metadata_json") from error
        require(isinstance(entry, dict) and entry.get("id") == identity
                and entry.get("catalogId") == identity and entry.get("builtIn") is True,
                f"{label} {identity}: stable ID/builtIn mismatch")
        provenance = entry.get("provenance")
        require(isinstance(provenance, dict), f"{label} {identity}: provenance missing")
        require(work_id == provenance.get("workId"), f"{label} {identity}: work_id mismatch")
        require(hash_value(content_hash, f"{label} {identity} content_hash")
                == hash_value(entry.get("resourceHash") or entry.get("hash"), f"{label} {identity} resourceHash"),
                f"{label} {identity}: content hash mismatch")
        require(hash_value(original_hash, f"{label} {identity} original_hash")
                == hash_value(entry.get("hash"), f"{label} {identity} hash"),
                f"{label} {identity}: original hash mismatch")
        edition = provenance.get("editionId")
        require(isinstance(edition, str) and edition and edition not in editions,
                f"{label} {identity}: duplicate/empty editionId")
        editions.add(edition)
        paths.add(relative.casefold())
        result[identity] = {"entry": entry, "relativePath": relative,
                            "contentHash": hash_value(content_hash, f"{identity} hash")}
    return result


def search_index_check(columns, rows, entries, label):
    require("entry_id" in columns, f"{label}: search index lacks entry_id")
    positions = {name: index for index, name in enumerate(columns)}
    seen = set()
    for row in rows:
        identity = row[positions["entry_id"]]
        require(identity in entries and identity not in seen, f"{label}: search index coverage/IDs mismatch")
        seen.add(identity)
        entry = entries[identity]["entry"]
        provenance = entry["provenance"]
        def check(name, expected):
            if name not in positions:
                return
            actual = row[positions[name]]
            if name == "duration" and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
                require(abs(actual - expected) <= TIMING_TOLERANCE_MS,
                        f"{label} {identity}: search index {name} mismatch")
            else:
                require(actual == expected,
                        f"{label} {identity}: search index {name} mismatch")
        check("duration", entry.get("durationMs"))
        check("provider", provenance.get("provider"))
        check("timing_verified", int(provenance.get("timingStatus") == "source-compared"))
        check("completeness", provenance.get("completeness"))
        check("human_reviewed", int(provenance.get("musicReview") not in REVIEW_NOT_REVIEWED))
    require(seen == set(entries), f"{label}: search index incomplete")


def score_files(root: Path):
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name == "catalog.db" or path.name.endswith(("-wal", "-shm", "-journal")):
            continue
        no_links(path)
        result[path.relative_to(root).as_posix().casefold()] = path
    return result


def snapshot_files(root: Path):
    return {key: sha256(path) for key, path in score_files(root).items()}


def compare_baseline_files(baseline: Path, stage: Path):
    before = snapshot_files(baseline)
    after = snapshot_files(stage)
    for relative, digest in before.items():
        require(relative in after, f"Baseline file missing from stage: {relative}")
        require(after[relative] == digest, f"Baseline score bytes changed: {relative}")
    return len(before)


def validate_version_fields(provenance, label):
    require(isinstance(provenance, dict), f"{label}: provenance missing")
    for field in VERSION_FIELDS:
        require(field in provenance, f"{label}: missing version field {field}")
        require(isinstance(provenance[field], str), f"{label}: version field {field} must be string")
        if field != "versionLabel":
            require(provenance[field].strip(), f"{label}: empty version field {field}")


def review_status_check(provenance, label):
    require(provenance.get("synthetic") is False, f"{label}: synthetic status is forbidden")
    require(provenance.get("timingStatus") == "source-compared", f"{label}: timing is not source-compared")
    require(provenance.get("musicReview") in REVIEW_NOT_REVIEWED,
            f"{label}: music review status is forged")
    require(provenance.get("gameReview") in GAME_NOT_TESTED,
            f"{label}: game test status is forged")
    require(provenance.get("redistributionVerified") is False,
            f"{label}: redistribution status is forged")


def build_report_check(stage: Path):
    report = stage / "build-report.json"
    if not report.exists():
        return None
    data = strict_json(report)
    require(not data.get("syntheticFixture", False), "Build report claims synthetic fixture")
    for key in ("musicReviewed", "musicReview", "gameTested", "realGameTested", "redistributionVerified"):
        value = data.get(key)
        require(value not in (True, "true", "human-reviewed", "reviewed", "tested"),
                f"Build report forges review/game/redistribution status: {key}")
    declared = data.get("smartInterludesDefault")
    if declared is not None:
        require(isinstance(declared, bool),
                "Build report smartInterludesDefault must be boolean when present")
    return declared

def audit(intake: Path, stage: Path, baseline: Path):
    intake, stage, baseline = map(lambda p: no_links(Path(p)), (intake, stage, baseline))
    require(intake.is_dir() and stage.is_dir() and baseline.is_dir(), "intake/stage/baseline must be directories")
    manifest_path = intake / "manifest.json"
    manifest = strict_json(manifest_path)
    require(isinstance(manifest, dict), "manifest.json must contain an object")
    raw_songs = manifest_value(manifest, "songs", "Songs", default=None)
    require(isinstance(raw_songs, list), "manifest.json must contain a songs/Songs list")
    songs = [normalize_manifest_song(item) for item in raw_songs]
    require(songs, "manifest songs list is empty")
    manifest_provider = manifest_value(manifest, "provider", "Provider", default=None)
    manifest_smart_default = manifest_value(
        manifest, "smartInterludesDefault", "SmartInterludesDefault", default=None)
    if manifest_smart_default is not None:
        require(isinstance(manifest_smart_default, bool),
                "manifest smartInterludesDefault must be boolean when present")
    manifest_ids, manifest_shas = set(), {}
    for item in songs:
        identity = item.get("id")
        require(isinstance(identity, str) and identity and identity not in manifest_ids,
                "manifest has duplicate/empty song ID")
        manifest_ids.add(identity)
        source_hash = hash_value(item.get("sourceSha256"), f"manifest {identity} sourceSha256")
        require(source_hash not in manifest_shas or item.get("editionId"),
                f"manifest {identity}: ambiguous duplicate source SHA without editionId")
        manifest_shas.setdefault(source_hash, []).append(item)

    stage_songs = stage / "Songs"
    require(stage_songs.is_dir(), "stage/Songs is missing")
    _, base_columns, base_rows, base_search = catalog_rows(baseline / "catalog.db")
    _, stage_columns, stage_rows, stage_search = catalog_rows(stage_songs / "catalog.db")
    baseline_entries = parse_entries(base_rows, "baseline catalogue")
    observed = parse_entries(stage_rows, "stage catalogue")
    require(len(observed) == len(baseline_entries) + len(songs),
            f"final count differs: expected {len(baseline_entries) + len(songs)}, got {len(observed)}")
    compare_baseline_files(baseline, stage_songs)
    search_index_check(stage_columns, stage_search, observed, "stage")

    baseline_by_path = {value["relativePath"].casefold(): value for value in baseline_entries.values()}
    stage_by_path = {value["relativePath"].casefold(): value for value in observed.values()}
    require(set(baseline_by_path) <= set(stage_by_path), "stage catalogue omits a baseline entry")
    for relative, before in baseline_by_path.items():
        after = stage_by_path[relative]
        require(same(canonical_existing_defaults(after["entry"]),
                     canonical_existing_defaults(before["entry"])),
                f"baseline metadata/defaults changed: {relative}")
    require(set(base_columns) == set(stage_columns), "baseline/stage search index schema differs")
    base_search_by_id = {row[base_columns.index("entry_id")]: dict(zip(base_columns, row)) for row in base_search}
    stage_search_by_id = {row[stage_columns.index("entry_id")]: dict(zip(stage_columns, row)) for row in stage_search}
    for identity in (value["entry"]["id"] for value in baseline_entries.values()):
        require(identity in stage_search_by_id and identity in base_search_by_id
                and same(stage_search_by_id[identity], base_search_by_id[identity]),
                f"baseline search index row changed: {identity}")

    build_smart_default = build_report_check(stage)
    if (manifest_smart_default is not None and build_smart_default is not None):
        require(manifest_smart_default == build_smart_default,
                "manifest/build report smartInterludesDefault mismatch")
    effective_smart_default = (manifest_smart_default
                               if manifest_smart_default is not None
                               else build_smart_default)
    manifest_dir = manifest_path.parent
    rows, seen_output = [], set()
    new_entries = [value for value in observed.values()
                   if value["relativePath"].casefold() not in baseline_by_path]
    require(len(new_entries) == len(songs), "new catalogue entry count does not equal manifest batch count")
    source_to_entries = {}
    for value in new_entries:
        entry = value["entry"]
        canonical_defaults(entry, expected_smart_interludes=effective_smart_default)
        provenance = entry["provenance"]
        validate_version_fields(provenance, f"new entry {entry['id']}")
        review_status_check(provenance, f"new entry {entry['id']}")
        source_to_entries.setdefault(provenance["sourceSha256"].upper(), []).append(value)

    for song in songs:
        identity = song["id"]
        source_path = resolve_manifest_path(intake, manifest_dir, song.get("midiPath") or song.get("sourcePath"),
                                            f"manifest {identity} MIDI")
        reference_path = resolve_manifest_path(intake, manifest_dir, song.get("referencePath"),
                                               f"manifest {identity} reference")
        source_hash = hash_value(song["sourceSha256"], f"manifest {identity} sourceSha256")
        require(sha256(source_path) == source_hash, f"manifest {identity}: source SHA mismatch")
        candidates = source_to_entries.get(source_hash, [])
        if len(candidates) != 1 and song.get("editionId"):
            candidates = [value for value in candidates
                          if value["entry"]["provenance"].get("editionId") == song["editionId"]]
        require(len(candidates) == 1, f"manifest {identity}: source does not map to one new entry")
        value = candidates[0]
        entry, provenance = value["entry"], value["entry"]["provenance"]
        require(value["relativePath"].casefold() not in seen_output, "duplicate stable output mapping")
        seen_output.add(value["relativePath"].casefold())
        require(provenance["sourceSha256"].upper() == source_hash,
                f"{identity}: normalized source SHA differs")
        if "sourceUrl" in song:
            require(provenance["sourceUrl"] == song["sourceUrl"], f"{identity}: sourceUrl differs")
        if manifest_provider is not None:
            require(provenance["provider"] == manifest_provider, f"{identity}: provider differs")
        for field in VERSION_FIELDS:
            if field in song:
                require(provenance[field] == song[field], f"{identity}: version field {field} differs")

        reference = strict_json(reference_path)
        independent = parse_smf(source_path.read_bytes())
        optional_reference_hash = reference.get("sourceSha256") or reference.get("sourceHash")
        if optional_reference_hash is not None:
            require(hash_value(optional_reference_hash, f"{identity} reference source SHA") == source_hash,
                    f"{identity}: reference source SHA differs")
        ref_compare = compare_timing(reference, independent, f"{identity} reference")
        normalized_path = stage_songs / value["relativePath"]
        require(sha256(normalized_path) == value["contentHash"], f"{identity}: normalized hash mismatch")
        normalized = strict_json(normalized_path)
        norm_compare = compare_timing(normalized, reference, f"{identity} normalized")
        require(normalized.get("provenance", {}).get("sourceSha256", "").upper() == source_hash,
                f"{identity}: normalized provenance source SHA differs")
        rows.append({"id": identity, "catalogId": entry["id"],
                     "relativePath": value["relativePath"], "sourceSha256": source_hash,
                     "editionId": provenance["editionId"], "workId": provenance["workId"],
                     "reference": ref_compare, "normalized": norm_compare})

    require(len(seen_output) == len(songs), "not every manifest item has a unique output")
    work_ids = sorted({row["workId"] for row in rows})
    edition_ids = sorted({row["editionId"] for row in rows})
    return {
        "status": "PASS_INDEPENDENT_POPBATCH_SOURCE_TIMING_ONLY",
        "evidenceClass": "INDEPENDENT_SOURCE_BYTES_AND_TIMING_ONLY",
        "baselineCount": len(baseline_entries), "batchCount": len(songs),
        "finalCount": len(observed), "uniqueNewWorks": len(work_ids),
        "uniqueNewEditions": len(edition_ids),
        "versionPolicy": "editionId identifies an entry; workId groups versions and is not counted as a new work per version",
        "baselineScoreBytesUnchanged": True, "baselineMetadataAndDefaultsUnchanged": True,
        "directoryEntriesHashesVerified": True, "searchIndexComplete": True,
        "smartInterludesDefault": effective_smart_default, "sourceTimingOnly": True,
        "musicReview": False, "gameTest": False, "redistributionVerified": False,
        "songs": rows,
        "evidenceBoundary": {
            "sourceTimingOnly": True, "musicReview": False, "gameTest": False,
            "redistribution": False,
            "boundary": "source timing/bytes and catalogue structure only; no music review, game test, redistribution clearance, audio playback, or deployment proof",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True, help="manifest directory containing manifest.json")
    parser.add_argument("--stage", type=Path, required=True, help="new staged directory containing Songs/catalog.db")
    parser.add_argument("--baseline", type=Path, required=True, help="unchanged baseline Songs directory")
    parser.add_argument("--report", type=Path, required=True, help="new JSON report; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        output = no_links(args.report)
        require(output.suffix.lower() == ".json" and output.parent.is_dir(),
                "report must be .json with an existing parent")
        require(not output.exists(), f"report already exists; refusing overwrite: {output}")
        for protected in (args.intake, args.stage, args.baseline):
            require(not output.resolve().is_relative_to(no_links(protected).resolve()),
                    "report must be outside intake/stage/baseline")
    except (OSError, AuditError) as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        result = audit(args.intake, args.stage, args.baseline)
        code = 0
    except Exception as error:
        result = {
            "status": "FAILED_INDEPENDENT_POPBATCH_AUDIT",
            "error": f"{type(error).__name__}: {error}",
            "sourceTimingOnly": False, "musicReview": False,
            "gameTest": False, "redistributionVerified": False,
            "evidenceBoundary": "failure; no positive source-timing or catalogue-completeness claim",
        }
        code = 1
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError as error:
        print(f"Unable to create new report: {error}", file=sys.stderr)
        return 2
    print(result["status"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
