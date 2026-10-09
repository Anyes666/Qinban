"""Read-only independent post-install verifier for a dynamic score batch.

This tool consumes a staged Songs catalogue, an updater PASS/applied report,
old catalogue backups, and the live runtime/source trees. It never imports the
updater, writes product files, opens UserData databases, starts processes, or
sends game input. It writes only a new JSON evidence/failure report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
SIDECARS = ("-wal", "-shm", "-journal")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class VerificationError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def _exists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _plain(path: Path) -> os.stat_result:
    try:
        info = Path(path).lstat()
    except FileNotFoundError as exc:
        raise VerificationError("Missing path: " + str(path)) from exc
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        raise VerificationError("Reparse path refused: " + str(path))
    if stat.S_ISREG(info.st_mode) and getattr(info, "st_nlink", 1) != 1:
        raise VerificationError("Hard-linked file refused: " + str(path))
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise VerificationError("Unsupported filesystem object: " + str(path))
    return info


def _directory(path: Path, label: str) -> Path:
    info = _plain(Path(path))
    if not stat.S_ISDIR(info.st_mode):
        raise VerificationError(f"{label} is not a directory: {path}")
    return Path(path)


def sha(path: Path) -> str:
    path = Path(path)
    before = _plain(path)
    if not stat.S_ISREG(before.st_mode):
        raise VerificationError("Expected regular file: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns):
            raise VerificationError("File raced before hashing: " + str(path))
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        if (after.st_ino, after.st_size, after.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns):
            raise VerificationError("File changed during hashing: " + str(path))
    final = _plain(path)
    if (final.st_ino, final.st_size, final.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns):
        raise VerificationError("File replaced during hashing: " + str(path))
    return digest.hexdigest().upper()


def snapshot(root: Path) -> dict[str, str]:
    root = _directory(Path(root), "snapshot root")
    result: dict[str, str] = {}

    def visit(directory: Path) -> None:
        _plain(directory)
        children = sorted((Path(e.path) for e in os.scandir(directory)), key=lambda item: item.name)
        for child in children:
            info = _plain(child)
            if stat.S_ISDIR(info.st_mode):
                visit(child)
            else:
                result[child.relative_to(root).as_posix()] = sha(child)

    visit(root)
    return result


def read_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise VerificationError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
    except VerificationError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError("Cannot read JSON " + str(path) + ": " + str(exc)) from exc


def write_new_json(path: Path, value: Any) -> None:
    path = Path(path).absolute()
    if _exists(path):
        raise VerificationError("Refusing to overwrite report: " + str(path))
    if not path.parent.exists():
        raise VerificationError("Report parent does not exist: " + str(path.parent))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise VerificationError("Invalid SHA256 for " + label)
    return value.upper()


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(os.path.abspath(os.fspath(right)))


def normal_snapshot(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise VerificationError(label + " must be a path-to-SHA256 object")
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw, value_hash in value.items():
        if not isinstance(raw, str) or not raw or "\\" in raw or raw.startswith("/") or raw.startswith("../") or "/../" in raw:
            raise VerificationError("Unsafe relative path in " + label + ": " + repr(raw))
        key = raw.replace("\\", "/")
        if key.casefold() in seen:
            raise VerificationError("Duplicate path in " + label + ": " + key)
        seen.add(key.casefold())
        result[key] = digest(value_hash, label + ":" + key)
    return result


def snapshot_diff(expected: dict[str, str], actual: dict[str, str]) -> dict[str, Any]:
    added = sorted(set(actual) - set(expected), key=str.casefold)
    removed = sorted(set(expected) - set(actual), key=str.casefold)
    changed = sorted((key for key in set(expected) & set(actual) if expected[key] != actual[key]), key=str.casefold)
    return {"ok": not (added or removed or changed), "addedCount": len(added), "removedCount": len(removed), "changedCount": len(changed), "added": added[:30], "removed": removed[:30], "changed": changed[:30]}
@dataclass(frozen=True)
class Catalog:
    path: Path
    sha256: str
    columns: tuple[str, ...]
    rows: dict[str, tuple[Any, ...]]
    entries: dict[str, tuple[str, str, dict[str, Any]]]
    search_columns: tuple[str, ...]
    search_rows: dict[str, tuple[Any, ...]]
    meta_rows: tuple[tuple[Any, ...], ...]


def score_path(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith(".json") or Path(value).name != value or value.rstrip(" .") != value:
        raise VerificationError("Invalid flat score path: " + repr(value))
    if any(char in value for char in '<>:"/\\|?*' + "".join(chr(i) for i in range(32))):
        raise VerificationError("Invalid score path: " + repr(value))
    return value


def catalog_location(source: Path) -> tuple[Path, Path | None]:
    source = Path(source)
    info = _plain(source)
    if stat.S_ISDIR(info.st_mode):
        return source / "catalog.db", source
    return source, None


def read_catalog(source: Path, *, verify_scores: bool) -> Catalog:
    catalog, score_root = catalog_location(Path(source))
    _plain(catalog)
    for suffix in SIDECARS:
        sidecar = catalog.with_name(catalog.name + suffix)
        if _exists(sidecar):
            raise VerificationError("Unexpected SQLite sidecar: " + str(sidecar))
    before = sha(catalog)
    try:
        db = sqlite3.connect(catalog.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as exc:
        raise VerificationError("Cannot open catalogue read-only: " + str(catalog)) from exc
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise VerificationError("SQLite integrity check failed: " + str(catalog))
        cursor = db.execute("SELECT * FROM entries")
        columns = tuple(field[0] for field in cursor.description)
        required = {"id", "relative_path", "content_hash", "metadata_json"}
        if not required.issubset(columns):
            raise VerificationError("Missing required entries columns: " + str(catalog))
        rows: dict[str, tuple[Any, ...]] = {}
        entries: dict[str, tuple[str, str, dict[str, Any]]] = {}
        paths: set[str] = set()
        for row in cursor.fetchall():
            values = dict(zip(columns, row))
            entry_id = values["id"]
            if not isinstance(entry_id, str) or not entry_id or entry_id in rows:
                raise VerificationError("Invalid/duplicate entry ID: " + repr(entry_id))
            relative = score_path(values["relative_path"])
            if relative.casefold() in paths:
                raise VerificationError("Duplicate score path: " + relative)
            paths.add(relative.casefold())
            content_hash = digest(values["content_hash"], relative)
            metadata_text = values["metadata_json"]
            if not isinstance(metadata_text, str):
                raise VerificationError("Metadata is not text: " + entry_id)
            try:
                metadata = json.loads(metadata_text)
            except json.JSONDecodeError as exc:
                raise VerificationError("Invalid metadata JSON: " + entry_id) from exc
            if not isinstance(metadata, dict):
                raise VerificationError("Metadata is not an object: " + entry_id)
            if verify_scores and score_root is not None and sha(score_root / relative) != content_hash:
                raise VerificationError("Score checksum mismatch: " + str(score_root / relative))
            rows[entry_id] = tuple(row)
            entries[entry_id] = (relative, content_hash, metadata)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        search_columns: tuple[str, ...] = ()
        search_rows: dict[str, tuple[Any, ...]] = {}
        if "search_index" in tables:
            cursor = db.execute("SELECT * FROM search_index")
            search_columns = tuple(field[0] for field in cursor.description)
            if "entry_id" not in search_columns:
                raise VerificationError("search_index lacks entry_id: " + str(catalog))
            entry_col = search_columns.index("entry_id")
            for row in cursor.fetchall():
                entry_id = row[entry_col]
                if entry_id not in entries or entry_id in search_rows:
                    raise VerificationError("Invalid/duplicate search row: " + repr(entry_id))
                search_rows[entry_id] = tuple(row)
            if set(search_rows) != set(entries):
                raise VerificationError("Incomplete search_index: " + str(catalog))
        meta_rows: tuple[tuple[Any, ...], ...] = ()
        if "meta" in tables:
            meta_rows = tuple(tuple(row) for row in db.execute("SELECT key,value FROM meta ORDER BY key"))
        result = Catalog(catalog, before, columns, rows, entries, search_columns, search_rows, meta_rows)
    except sqlite3.Error as exc:
        raise VerificationError("Catalogue query failed: " + str(catalog)) from exc
    finally:
        db.close()
    if sha(catalog) != before:
        raise VerificationError("Catalogue changed during read: " + str(catalog))
    return result


def catalog_equal(left: Catalog, right: Catalog) -> bool:
    return (left.columns == right.columns and left.rows == right.rows and left.search_columns == right.search_columns and left.search_rows == right.search_rows and left.meta_rows == right.meta_rows)


def compare_old_rows(baseline: Catalog, candidate: Catalog, label: str) -> dict[str, Any]:
    missing = sorted(set(baseline.rows) - set(candidate.rows))
    changed = sorted(key for key in baseline.rows if candidate.rows.get(key) != baseline.rows[key])
    missing_search = sorted(set(baseline.search_rows) - set(candidate.search_rows))
    changed_search = sorted(key for key in baseline.search_rows if candidate.search_rows.get(key) != baseline.search_rows[key])
    base_meta, candidate_meta = dict(baseline.meta_rows), dict(candidate.meta_rows)
    changed_meta = sorted(key for key, value in base_meta.items() if candidate_meta.get(key) != value)
    if missing or changed or missing_search or changed_search or changed_meta:
        raise VerificationError("Original " + label + " rows/defaults/search rows changed", {"missing": missing[:30], "changed": changed[:30], "missingSearch": missing_search[:30], "changedSearch": changed_search[:30], "changedMeta": changed_meta[:30]})
    return {"entryRowsByteExact": True, "metadataAndDefaultsByteExact": True, "searchRowsByteExact": True, "existingMetaKeysByteExact": True, "protectedEntryCount": len(baseline.rows), "protectedSearchRowCount": len(baseline.search_rows)}


def report_path(report: dict[str, Any], key: str) -> Path:
    value = report.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VerificationError("Installation report missing path: " + key)
    return Path(value)


def resolve_baseline(label: str, explicit: Path | None, report: dict[str, Any], backup: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    values = report.get("baselineCatalogs")
    if isinstance(values, dict) and isinstance(values.get(label), str):
        return Path(values[label])
    candidate = Path(backup) / (label + "-catalog.db") if backup is not None else None
    if candidate is not None and _exists(candidate):
        return candidate
    raise VerificationError("Missing baseline " + label + " catalogue; pass --baseline-" + label + "-catalog or provide backup/" + label + "-catalog.db")


def operation_map(report: dict[str, Any], runtime: Path, source: Path) -> dict[str, dict[str, Any]]:
    operations = report.get("operations")
    if not isinstance(operations, list):
        raise VerificationError("Installation report has no operations")
    targets = {"runtime": runtime / "Songs", "source": source}
    result: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("target"), str):
            raise VerificationError("Invalid installation operation")
        labels = [label for label, target in targets.items() if same_path(Path(operation["target"]), target)]
        if len(labels) != 1 or labels[0] in result:
            raise VerificationError("Operations do not uniquely cover runtime and source")
        result[labels[0]] = operation
    if set(result) != set(targets):
        raise VerificationError("Installation report is missing runtime/source operation")
    return result


def manifest_scores(report: dict[str, Any]) -> dict[str, tuple[str, str]]:
    manifest = report.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("scores"), list):
        raise VerificationError("Installation report manifest.scores is missing")
    result: dict[str, tuple[str, str]] = {}
    for item in manifest["scores"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in result:
            raise VerificationError("Invalid/duplicate manifest score")
        relative = score_path(item.get("relativePath"))
        result[item["id"]] = (relative, digest(item.get("contentSha256"), relative))
    return result

def expected_after(base: dict[str, str], stage: Catalog, new_ids: set[str], prefix: str, stage_files: dict[str, str]) -> dict[str, str]:
    expected = dict(base)
    expected["Songs/catalog.db" if prefix else "catalog.db"] = stage.sha256
    for entry_id in sorted(new_ids):
        relative, content_hash, _ = stage.entries[entry_id]
        key = prefix + relative
        if key in base:
            raise VerificationError("New score already exists in baseline: " + key)
        if stage_files.get(relative) != content_hash:
            raise VerificationError("Stage score hash mismatch: " + relative)
        expected[key] = content_hash
    return expected


def load_distribution_dirs(path: Path) -> set[str]:
    value = read_json(path)
    if isinstance(value, dict):
        value = value.get("directories")
    if not isinstance(value, list) or any(not isinstance(item, str) or Path(item).name != item or "/" in item or "\\" in item for item in value):
        raise VerificationError("Distribution baseline must be a list of immediate directory names")
    return {item.casefold() for item in value}


def current_distribution_dirs(root: Path) -> set[str]:
    _directory(root, "distribution root")
    result: set[str] = set()
    for entry in os.scandir(root):
        path = Path(entry.path)
        info = _plain(path)
        if stat.S_ISDIR(info.st_mode):
            result.add(path.name.casefold())
    return result


def verify_installation(*, stage_songs: Path, runtime: Path, source_songs: Path, installation_report: Path, baseline_runtime_catalog: Path | None = None, baseline_source_catalog: Path | None = None, baseline_runtime_snapshot: Path | None = None, baseline_source_snapshot: Path | None = None, distribution_before: Path | None = None, distribution_root: Path | None = None) -> dict[str, Any]:
    stage_songs = _directory(Path(stage_songs), "stage Songs")
    runtime = _directory(Path(runtime), "runtime")
    source_songs = _directory(Path(source_songs), "source Songs")
    installation_path = Path(installation_report)
    _plain(installation_path)
    report = read_json(installation_path)
    if not isinstance(report, dict):
        raise VerificationError("Installation report must be an object")
    if report.get("status") != "PASS" or report.get("applied") is not True:
        raise VerificationError("Installation report is not PASS/applied", {"status": report.get("status"), "applied": report.get("applied")})
    if report.get("preflightReady") is not True:
        raise VerificationError("Installation report lacks preflightReady=true")
    if not same_path(report_path(report, "runtime"), runtime) or not same_path(report_path(report, "source"), source_songs):
        raise VerificationError("CLI runtime/source does not match installation report")

    backup_value = report.get("backup")
    backup = Path(backup_value) if isinstance(backup_value, str) and backup_value else None
    operations = operation_map(report, runtime, source_songs)
    stage = read_catalog(stage_songs, verify_scores=True)
    actual_runtime = read_catalog(runtime / "Songs", verify_scores=True)
    actual_source = read_catalog(source_songs, verify_scores=True)
    baseline_runtime_path = resolve_baseline("runtime", baseline_runtime_catalog, report, backup)
    baseline_source_path = resolve_baseline("source", baseline_source_catalog, report, backup)
    baseline_runtime = read_catalog(baseline_runtime_path, verify_scores=False)
    baseline_source = read_catalog(baseline_source_path, verify_scores=False)

    if not catalog_equal(baseline_runtime, baseline_source):
        raise VerificationError("Runtime/source baseline catalogues differ")
    if not catalog_equal(actual_runtime, stage) or not catalog_equal(actual_source, stage):
        raise VerificationError("Installed runtime/source catalogues do not equal stage")
    if set(baseline_runtime.rows) - set(stage.rows):
        raise VerificationError("Stage removed existing catalogue entries")
    baseline_count = len(baseline_runtime.rows)
    final_count = len(stage.rows)
    new_ids = set(stage.rows) - set(baseline_runtime.rows)
    batch_count = len(new_ids)
    if final_count != baseline_count + batch_count:
        raise VerificationError("Derived final count is not baseline plus batch")

    stage_files = snapshot(stage_songs)
    if set(stage_files) != ({"catalog.db"} | {entry[0] for entry in stage.entries.values()}):
        raise VerificationError("Stage contains files other than catalog.db and catalog score files")
    stage_old = compare_old_rows(baseline_runtime, stage, "stage")
    runtime_old = compare_old_rows(baseline_runtime, actual_runtime, "runtime")
    source_old = compare_old_rows(baseline_source, actual_source, "source")

    manifest = report.get("manifest")
    if not isinstance(manifest, dict) or (manifest.get("entries"), manifest.get("newEntries")) != (final_count, batch_count):
        raise VerificationError("Manifest counts do not match stage-derived baseline/batch/final")
    if report.get("newBuiltinCount") != batch_count:
        raise VerificationError("newBuiltinCount does not match derived batch count")
    if digest(manifest.get("catalogSha256"), "manifest.catalogSha256") != stage.sha256:
        raise VerificationError("Manifest catalog SHA does not match stage")
    if isinstance(manifest.get("source"), str) and not same_path(Path(manifest["source"]), stage_songs):
        raise VerificationError("Manifest source does not match stage Songs")
    if manifest_scores(report) != {key: (value[0], value[1]) for key, value in stage.entries.items()}:
        raise VerificationError("Manifest scores do not exactly describe stage")

    expected_new = {stage.entries[key][0] for key in new_ids}
    operation_result: dict[str, Any] = {}
    for label, operation in operations.items():
        if (operation.get("oldEntries"), operation.get("newEntries"), operation.get("newEntriesThisBatch")) != (baseline_count, final_count, batch_count):
            raise VerificationError(label + " operation counts do not match derived counts")
        added = operation.get("addFiles")
        if not isinstance(added, list) or len(added) != batch_count or {str(item).casefold() for item in added} != {item.casefold() for item in expected_new}:
            raise VerificationError(label + " operation does not add exactly the new score set")
        operation_result[label] = {"oldEntries": baseline_count, "newEntries": final_count, "newEntriesThisBatch": batch_count, "newScoreFiles": batch_count}

    runtime_base = normal_snapshot(read_json(baseline_runtime_snapshot), "runtimeSnapshot") if baseline_runtime_snapshot else normal_snapshot(report.get("runtimeSnapshot"), "runtimeSnapshot")
    source_base = normal_snapshot(read_json(baseline_source_snapshot), "sourceSnapshot") if baseline_source_snapshot else normal_snapshot(report.get("sourceSnapshot"), "sourceSnapshot")
    if runtime_base.get("Songs/catalog.db") != baseline_runtime.sha256 or source_base.get("catalog.db") != baseline_source.sha256:
        raise VerificationError("Report baseline snapshot catalog hash disagrees with backup catalog")
    for relative, content_hash, _ in baseline_runtime.entries.values():
        if runtime_base.get("Songs/" + relative) != content_hash:
            raise VerificationError("Runtime baseline snapshot disagrees with old score: " + relative)
    for relative, content_hash, _ in baseline_source.entries.values():
        if source_base.get(relative) != content_hash:
            raise VerificationError("Source baseline snapshot disagrees with old score: " + relative)

    runtime_now = snapshot(runtime)
    source_now = snapshot(source_songs)
    expected_runtime = expected_after(runtime_base, stage, new_ids, "Songs/", stage_files)
    expected_source = expected_after(source_base, stage, new_ids, "", stage_files)
    runtime_diff, source_diff = snapshot_diff(expected_runtime, runtime_now), snapshot_diff(expected_source, source_now)
    if not runtime_diff["ok"] or not source_diff["ok"]:
        raise VerificationError("Live filesystem delta is not exactly catalog replacement plus new score files", {"runtime": runtime_diff, "source": source_diff})
    after = report.get("after")
    if isinstance(after, dict):
        for label, actual in (("runtime", runtime_now), ("source", source_now)):
            if isinstance(after.get(label), dict) and normal_snapshot(after[label], "after." + label) != actual:
                raise VerificationError("Report after snapshot disagrees with live tree: " + label)

    exe_keys = [key for key in runtime_base if key.casefold().endswith("qinban.exe")]
    if len(exe_keys) != 1 or runtime_now.get(exe_keys[0]) != runtime_base[exe_keys[0]] or report.get("exeUnchanged") is not True:
        raise VerificationError("QinBan.exe SHA256 is not proven unchanged")
    user_keys = {key for key in runtime_base if key.casefold().startswith("userdata/")}
    if {key: runtime_now[key] for key in user_keys} != {key: runtime_base[key] for key in user_keys} or report.get("userDataUnchanged") is not True or report.get("actualUserDataDatabasesOpened") is not False:
        raise VerificationError("UserData changed or report does not attest untouched UserData")

    sidecars = [str(root / ("catalog.db" + suffix)) for root in (stage_songs, runtime / "Songs", source_songs) for suffix in SIDECARS if _exists(root / ("catalog.db" + suffix))]
    if sidecars:
        raise VerificationError("SQLite sidecar files are present", {"sidecars": sidecars})
    if report.get("nativeKeySendAttempts") != 0:
        raise VerificationError("nativeKeySendAttempts is not zero")
    if report.get("newDistributionFolderCreated") is not False:
        raise VerificationError("newDistributionFolderCreated is not false")

    dist_root = Path(distribution_root) if distribution_root else runtime.parent
    if not same_path(dist_root, runtime.parent):
        raise VerificationError("distribution root must be runtime parent")
    distribution_evidence = "installation-report-flag-only"
    if distribution_before:
        if current_distribution_dirs(dist_root) != load_distribution_dirs(Path(distribution_before)):
            raise VerificationError("Distribution directory inventory changed")
        distribution_evidence = "independent-directory-inventory"

    if backup is not None and _exists(backup / "before.json"):
        before = read_json(backup / "before.json")
        if isinstance(before, dict) and isinstance(before.get("states"), dict):
            for label, current_base in (("runtime", runtime_base), ("source", source_base)):
                state = before["states"].get(label)
                if isinstance(state, dict) and isinstance(state.get("files"), dict) and normal_snapshot(state["files"], "backup.before." + label) != current_base:
                    raise VerificationError("backup/before.json disagrees with installation report: " + label)

    return {
        "status": "PASS_INDEPENDENT_POPBATCH_INSTALLATION",
        "evidenceClass": "INDEPENDENT_POST_INSTALL_SOURCE_CATALOG_AND_FILESYSTEM_ONLY",
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "inputs": {"stageSongs": str(stage_songs), "installationReport": str(installation_path), "runtime": str(runtime), "sourceSongs": str(source_songs), "baselineRuntimeCatalog": str(baseline_runtime_path), "baselineSourceCatalog": str(baseline_source_path), "distributionRoot": str(dist_root), "distributionBefore": str(distribution_before) if distribution_before else None},
        "counts": {"baseline": baseline_count, "batch": batch_count, "final": final_count, "stageActual": len(stage.rows), "runtimeActual": len(actual_runtime.rows), "sourceActual": len(actual_source.rows)},
        "operations": operation_result,
        "checks": {"stageOnlyCatalogAndScores": True, "runtimeCatalogEqualsStage": True, "sourceCatalogEqualsStage": True, "baselineStageRowsAndDefaultsByteExact": stage_old, "baselineRuntimeRowsAndDefaultsByteExact": runtime_old, "baselineSourceRowsAndDefaultsByteExact": source_old, "runtimeExactAllowedDelta": runtime_diff, "sourceExactAllowedDelta": source_diff, "qInBanExeSha256Unchanged": True, "userDataUnchanged": True, "catalogSidecarsAbsent": True, "distributionDirectoryEvidence": distribution_evidence, "nativeKeySendAttemptsZero": True},
        "catalogSha256": stage.sha256,
        "qInBanExe": {"relativePath": exe_keys[0], "sha256": runtime_now[exe_keys[0]]},
        "newScoreFiles": sorted(expected_new, key=str.casefold),
        "newScoreFileCount": batch_count,
        "nativeKeySendAttempts": 0,
        "actualUserDataDatabasesOpened": False,
        "checkerOpenedUserDataDatabases": False,
        "gameInputTouched": False,
        "newDistributionFolderCreated": False,
        "musicReviewed": False,
        "gameTested": False,
        "redistributionVerified": False,
        "evidenceBoundary": "This proves the additive installed catalogue/filesystem contract only; it does not prove musical quality, game playback, or redistribution rights.",
    }

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-songs", required=True, type=Path)
    parser.add_argument("--installation-report", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--source-songs", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path, help="New output JSON; existing files are never overwritten")
    parser.add_argument("--baseline-runtime-catalog", type=Path, help="Defaults to installation-report backup/runtime-catalog.db")
    parser.add_argument("--baseline-source-catalog", type=Path, help="Defaults to installation-report backup/source-catalog.db")
    parser.add_argument("--baseline-runtime-snapshot", type=Path)
    parser.add_argument("--baseline-source-snapshot", type=Path)
    parser.add_argument("--distribution-before", type=Path, help="Optional JSON list or {directories:[...]} captured before install")
    parser.add_argument("--distribution-root", type=Path, help="Defaults to runtime parent")
    return parser


def failure_report(args: argparse.Namespace, error: BaseException) -> dict[str, Any]:
    return {"status": "FAIL_INSTALLATION_CHECK", "evidenceClass": "INDEPENDENT_POST_INSTALL_SOURCE_CATALOG_AND_FILESYSTEM_ONLY", "atUtc": datetime.now(timezone.utc).isoformat(), "inputs": {"stageSongs": str(args.stage_songs), "installationReport": str(args.installation_report), "runtime": str(args.runtime), "sourceSongs": str(args.source_songs), "report": str(args.report)}, "errorType": type(error).__name__, "error": str(error), "details": getattr(error, "details", {}), "nativeKeySendAttempts": None, "actualUserDataDatabasesOpened": False, "checkerOpenedUserDataDatabases": False, "gameInputTouched": False, "evidenceBoundary": "Verification failed; no pass claim and no runtime/source/UserData write was attempted."}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.report).absolute()
    try:
        if _exists(output):
            raise VerificationError("Refusing to overwrite report: " + str(output))
        result = verify_installation(stage_songs=args.stage_songs, runtime=args.runtime, source_songs=args.source_songs, installation_report=args.installation_report, baseline_runtime_catalog=args.baseline_runtime_catalog, baseline_source_catalog=args.baseline_source_catalog, baseline_runtime_snapshot=args.baseline_runtime_snapshot, baseline_source_snapshot=args.baseline_source_snapshot, distribution_before=args.distribution_before, distribution_root=args.distribution_root)
        write_new_json(output, result)
    except Exception as error:
        try:
            write_new_json(output, failure_report(args, error))
        except Exception as report_error:
            print("FAIL: cannot write failure report: " + repr(report_error), file=sys.stderr)
        print("FAIL_INSTALLATION_CHECK: " + str(error), file=sys.stderr)
        return 1
    print("PASS_INDEPENDENT_POPBATCH_INSTALLATION: baseline=" + str(result["counts"]["baseline"]) + " batch=" + str(result["counts"]["batch"]) + " final=" + str(result["counts"]["final"]) + "; native=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
