"""Deterministic BFDB ABC-to-MIDI candidate intake for QinBan.

The source is a pinned Zenodo BFDB archive. This tool converts selected ABC
files with a locally pinned music21 runtime, then independently parses the
produced SMF before writing a new catalog-intake directory. It never touches
Songs, an EXE, UserData, a game process, native input, or privileges.

The BFDB record is CC BY-NC 4.0 at the dataset level. That declaration is
preserved as candidate metadata and is not treated as automatic clearance for
bundled redistribution or for the underlying folk works.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import warnings
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT.parent / ".tools" / "sources" / "bfdb-zenodo-14692025-2026-10-06"
ZENODO_RECORD_URL = "https://zenodo.org/records/14692025"
ZENODO_ABC_URL = "https://zenodo.org/records/14692025/files/tune_abc_files.zip"
LICENSE = "CC BY-NC 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
SOURCE_COMMIT = "zenodo-14692025"
BATCH_KIND = "bfdb-abc-to-midi-candidate-intake"
MAX_MIDI_BYTES = 16 * 1024 * 1024
MAX_DURATION_MS = 1_800_000
MIN_BPM = 20.0
MAX_BPM = 400.0
MAX_TITLE = 180
SOURCE_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
INVALID_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class IntakeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _write_new(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise IntakeError(f"refusing to overwrite existing output: {path}")
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug(value: str, fallback: str = "unknown") -> str:
    text = unicodedata.normalize("NFKD", _raw(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or fallback)[:96]


def _bounded_title(title: str, abc_hash: str) -> str:
    title = _raw(title) or f"BFDB tune {abc_hash[:8]}"
    if len(title) <= MAX_TITLE:
        return title
    suffix = f" … {abc_hash[:8]}"
    return title[: MAX_TITLE - len(suffix)].rstrip() + suffix


def _validate_display_text(value: str, field: str) -> None:
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise IntakeError(f"{field} contains a control character")


def _valid_http(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _load_exclusions(paths: Iterable[str | Path]) -> dict[str, set[str]]:
    source_hashes: set[str] = set()
    edition_ids: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            path = path / "manifest.json"
        if not path.is_file():
            raise IntakeError(f"exclude manifest does not exist: {path}")
        payload = _read_json(path)
        songs = payload.get("Songs") or payload.get("songs") or []
        for song in songs:
            if not isinstance(song, dict):
                continue
            for key in ("SourceSha256", "sourceSha256", "source_sha256"):
                value = _raw(song.get(key)).upper()
                if SOURCE_HASH_RE.fullmatch(value):
                    source_hashes.add(value)
                    break
            for key in ("EditionId", "editionId", "edition_id"):
                value = _raw(song.get(key))
                if value:
                    edition_ids.add(value.casefold())
                    break
    return {"sourceHashes": source_hashes, "editionIds": edition_ids}


def _load_music21(path: Path | None) -> tuple[Any, str]:
    if path is not None:
        path = path.resolve()
        if not path.is_dir():
            raise IntakeError(f"music21 package path does not exist: {path}")
        sys.path.insert(0, str(path))
    try:
        import music21  # type: ignore
        from music21 import converter  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise IntakeError(f"music21 is required for BFDB conversion: {exc}") from exc
    return converter, str(getattr(music21, "__version__", "unknown"))


def _load_metadata(source_root: Path) -> dict[str, dict[str, str]]:
    csv_path = source_root / "dataset.csv"
    if not csv_path.is_file():
        raise IntakeError(f"missing BFDB dataset.csv: {csv_path}")
    result: dict[str, dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            name = _raw(row.get("filename"))
            if name:
                result[name.casefold()] = {str(k): _raw(v) for k, v in row.items()}
    return result


def _zip_members(source_root: Path) -> list[str]:
    zip_path = source_root / "tune_abc_files.zip"
    if not zip_path.is_file():
        raise IntakeError(f"missing BFDB archive: {zip_path}")
    with zipfile.ZipFile(zip_path) as archive:
        names = [
            name for name in archive.namelist()
            if name.startswith("tune_abc_files/")
            and name.lower().endswith(".abc")
            and not name.endswith("/")
        ]
    return sorted(names, key=lambda value: value.casefold())


def _abc_title(abc_text: str) -> str:
    for line in abc_text.splitlines():
        if line.startswith("T:") and _raw(line[2:]):
            return _raw(line[2:])
    return ""


def _convert_abc(converter: Any, abc_text: str, destination: Path) -> tuple[bytes, list[str]]:
    captured: list[str] = []
    with warnings.catch_warnings(record=True) as warning_list:
        warnings.simplefilter("always")
        score = converter.parseData(abc_text, format="abc")
        for warning in warning_list:
            captured.append(str(warning.message))
    destination.parent.mkdir(parents=True, exist_ok=True)
    score.write("midi", fp=str(destination))
    return destination.read_bytes(), captured


def _work_identity(title: str, artist: str) -> str:
    return f"bfdb-work:{_slug(title)}::{_slug(artist, 'unknown-source')}"


def _validate_source_reference(reference: dict[str, Any]) -> None:
    notes = reference.get("notes") or []
    if not notes:
        raise IntakeError("independent SMF parser returned no notes")
    bpm = float(reference.get("bpm", 0))
    if not math.isfinite(bpm) or bpm < MIN_BPM or bpm > MAX_BPM:
        raise IntakeError(f"BPM outside QinBan budget: {bpm}")
    length_ms = float(reference.get("lengthMs", 0))
    if not math.isfinite(length_ms) or length_ms <= 0 or length_ms > MAX_DURATION_MS:
        raise IntakeError(f"length outside QinBan budget: {length_ms}")


def _build_reference(midi_bytes: bytes, label: str) -> dict[str, Any]:
    try:
        from smf_reference import parse_smf
    except ModuleNotFoundError:
        from tools.smf_reference import parse_smf
    if len(midi_bytes) > MAX_MIDI_BYTES:
        raise IntakeError(f"MIDI exceeds {MAX_MIDI_BYTES} bytes")
    reference = parse_smf(midi_bytes)
    _validate_source_reference(reference)
    reference["referenceSchema"] = "bfdb-independent-smf-reference-v1"
    reference["sourceLabel"] = label
    return reference


def _contract_song(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "Id": item["id"],
        "Title": item["title"],
        "Artist": item["artist"],
        "MidiPath": item["midiPath"],
        "ReferencePath": item["referencePath"],
        "SourceUrl": item["sourceUrl"],
        "SourceSha256": item["sourceSha256"],
        "LanguageTags": [],
        "Artists": [item["artist"]],
        "Provider": "BFDB",
        "SourceCommit": SOURCE_COMMIT,
        "SourceRecord": ZENODO_RECORD_URL,
        "BatchKind": BATCH_KIND,
        "Author": "BFDB dataset authors / source transcriber",
        "Category": "BFDB British folk candidate",
        "Description": "BFDB ABC-to-MIDI structural candidate; rights, music, and game review pending",
        "IdPattern": "bfdb-<abc-sha256-prefix>",
        "SmartInterludes": True,
        "WorkId": item["workId"],
        "EditionId": item["editionId"],
        "VersionLabel": item["versionLabel"],
        "License": LICENSE,
        "LicenseUrl": LICENSE_URL,
        "RightsStatus": "candidate-unverified",
        "RightsNote": item["rightsNote"],
        "Album": "",
        "Aliases": [],
        "Tags": ["bfdb", "folk", "abc", "candidate"],
        "Completeness": "source-abc-to-midi",
        "MusicReview": "not-reviewed",
        "GameReview": "not-tested",
        "RedistributionVerified": False,
    }


def acquire_batch(
    source_root: Path,
    output: Path,
    *,
    limit: int = 100,
    offset: int = 0,
    exclude_manifests: Iterable[str | Path] = (),
    music21_path: Path | None = None,
    enforce_output_root: bool = True,
    now_fn=utc_now,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    output = output.resolve()
    if limit <= 0 or offset < 0:
        raise IntakeError("limit must be positive and offset must be non-negative")
    if not source_root.is_dir():
        raise IntakeError(f"source root does not exist: {source_root}")
    if output.exists():
        raise IntakeError(f"refusing existing output: {output}")
    catalog_root = (ROOT / "catalog-intake").resolve()
    if enforce_output_root and not output.is_relative_to(catalog_root):
        raise IntakeError(f"output must be under catalog-intake: {output}")
    converter, music21_version = _load_music21(music21_path)
    metadata = _load_metadata(source_root)
    members = _zip_members(source_root)
    exclusions = _load_exclusions(exclude_manifests)
    selected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_midi: set[str] = set(exclusions["sourceHashes"])
    seen_editions: set[str] = set(exclusions["editionIds"])
    valid_seen = 0

    with zipfile.ZipFile(source_root / "tune_abc_files.zip") as archive, tempfile.TemporaryDirectory(prefix="bfdb-midi-") as temp:
        temp_root = Path(temp)
        for member in members:
            name = Path(member).name
            try:
                abc_bytes = archive.read(member)
                abc_hash = sha256_bytes(abc_bytes)
                row = metadata.get(name.casefold()) or metadata.get(name.casefold().replace("tune_abc_files/", ""))
                if row is None:
                    row = metadata.get(name.replace("tune_abc_files/", "").casefold(), {})
                abc_text = abc_bytes.decode("utf-8-sig")
                title = _bounded_title(_raw(row.get("title")) or _abc_title(abc_text), abc_hash)
                _validate_display_text(title, "title")
                artist_raw = _raw(row.get("composer/performer"))
                if artist_raw.upper() in {"", "N/A", "NA", "UNKNOWN"}:
                    artist_raw = "Unknown / not supplied by BFDB"
                _validate_display_text(artist_raw, "artist")
                work_id = _work_identity(title, artist_raw)
                edition_id = f"bfdb:14692025:{abc_hash[:24].lower()}"
                if edition_id.casefold() in seen_editions:
                    failures.append({"member": member, "stage": "dedupe", "error": "duplicate EditionId"})
                    continue
                midi_path = temp_root / f"{abc_hash}.mid"
                midi_bytes, warnings_seen = _convert_abc(converter, abc_text, midi_path)
                midi_hash = sha256_bytes(midi_bytes)
                if midi_hash in seen_midi:
                    failures.append({"member": member, "stage": "dedupe", "error": "duplicate MIDI SHA256"})
                    continue
                reference = _build_reference(midi_bytes, member)
                seen_midi.add(midi_hash)
                seen_editions.add(edition_id.casefold())
                if valid_seen < offset:
                    valid_seen += 1
                    continue
                source_name = _raw(row.get("filename")) or name
                year = _raw(row.get("year")) or "year-unknown"
                version_label = f"BFDB {year} / {source_name} / abc-{abc_hash[:8]}"
                _validate_display_text(version_label, "version label")
                source_url = _raw(row.get("source"))
                if not _valid_http(source_url):
                    source_url = ZENODO_ABC_URL
                item_id = f"bfdb-{abc_hash[:20].lower()}"
                item = {
                    "id": item_id,
                    "title": title,
                    "artist": artist_raw,
                    "workId": work_id,
                    "editionId": edition_id,
                    "versionLabel": version_label[:256],
                    "sourceSha256": midi_hash,
                    "abcSha256": abc_hash,
                    "abcBytes": abc_bytes,
                    "midiBytes": midi_bytes,
                    "reference": reference,
                    "warnings": warnings_seen,
                    "sourceName": source_name,
                    "sourceUrl": source_url,
                    "csvRow": row,
                    "rightsNote": "BFDB declares CC BY-NC 4.0 at dataset level; underlying tune rights and bundled redistribution scope remain unverified.",
                }
                selected.append(item)
                valid_seen += 1
                if len(selected) >= limit:
                    break
            except Exception as exc:
                failures.append({"member": member, "stage": "convert-or-validate", "error": str(exc)})

        if len(selected) != limit:
            raise IntakeError(f"only {len(selected)} acceptable candidates after conversion; need {limit}; failures={len(failures)}")

        retrieved_at = now_fn()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()
        for folder in ("midi", "references", "source/abc", "metadata/records"):
            (output / folder).mkdir(parents=True, exist_ok=True)
        songs: list[dict[str, Any]] = []
        version_groups: dict[str, list[dict[str, str]]] = {}
        for item in selected:
            midi_path = output / "midi" / f"{item['id']}.mid"
            reference_path = output / "references" / f"{item['id']}.json"
            abc_path = output / "source" / "abc" / f"{item['id']}.abc"
            metadata_path = output / "metadata" / "records" / f"{item['id']}.json"
            _write_new(midi_path, item["midiBytes"])
            _write_new(reference_path, json.dumps(item["reference"], ensure_ascii=False, indent=2) + "\n")
            _write_new(abc_path, item["abcBytes"])
            record = {
                "schema": "bfdb-candidate-record-v1",
                "provider": "BFDB",
                "sourceRecord": ZENODO_RECORD_URL,
                "sourceArchive": "tune_abc_files.zip",
                "sourceMember": item["sourceName"],
                "sourceUrl": item["sourceUrl"],
                "abcSha256": item["abcSha256"],
                "midiSha256": item["sourceSha256"],
                "csvRow": item["csvRow"],
                "derived": {"workId": item["workId"], "editionId": item["editionId"], "versionLabel": item["versionLabel"], "music21Version": music21_version},
                "rights": {"license": LICENSE, "licenseUrl": LICENSE_URL, "status": "candidate-unverified", "redistributionVerified": False, "note": item["rightsNote"]},
                "evidence": {"referencePath": str(reference_path.resolve()), "warnings": item["warnings"], "timing": "independent smf_reference.parse_smf"},
            }
            _write_new(metadata_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            contract = dict(item)
            contract.update({"midiPath": str(midi_path.resolve()), "referencePath": str(reference_path.resolve())})
            songs.append(_contract_song(contract))
            version_groups.setdefault(item["workId"], []).append({"id": item["id"], "editionId": item["editionId"], "versionLabel": item["versionLabel"], "title": item["title"], "artist": item["artist"]})

        manifest = {
            "Songs": songs,
            "SourceCommit": SOURCE_COMMIT,
            "SourceRecord": ZENODO_RECORD_URL,
            "RetrievedAtUtc": retrieved_at,
            "Provider": "BFDB",
            "BatchKind": BATCH_KIND,
            "SourceUrl": ZENODO_ABC_URL,
            "License": LICENSE,
            "LicenseUrl": LICENSE_URL,
            "RightsStatus": "candidate-unverified",
            "RightsNote": "Dataset license and underlying folk-tune rights remain subject to manual review; no public redistribution clearance is asserted.",
            "RedistributionVerified": False,
            "Author": "BFDB dataset authors / source transcriber",
            "Category": "BFDB British folk candidate",
            "Description": "ABC-to-MIDI structural candidate batch; no human music/game/rights review",
            "IdPattern": "bfdb-<abc-sha256-prefix>",
            "SmartInterludesDefault": True,

        }
        report = {
            "status": "PASS_BFDB_ABC_TO_MIDI_CANDIDATE_INTAKE",
            "provider": "BFDB",
            "sourceRecord": ZENODO_RECORD_URL,
            "sourceArchive": str((source_root / "tune_abc_files.zip").resolve()),
            "sourceArchiveSha256": sha256_file(source_root / "tune_abc_files.zip"),
            "sourceMetadata": str((source_root / "dataset.csv").resolve()),
            "sourceMetadataSha256": sha256_file(source_root / "dataset.csv"),
            "music21Version": music21_version,
            "selectedCount": len(selected),
            "candidateMemberCount": len(members),
            "conversionFailureCount": len(failures),
            "conversionFailures": failures,
            "uniqueSourceSha256": len({item["sourceSha256"] for item in selected}),
            "uniqueEditionIds": len({item["editionId"] for item in selected}),
            "rightsStatus": "candidate-unverified",
            "musicReview": "not-reviewed",
            "gameReview": "not-tested",
            "redistributionVerified": False,
            "nativeInputAttempts": 0,
            "evidenceBoundary": "ABC source, dataset metadata, music21 conversion, and independent SMF timing only; no human listening, game, or rights certification.",
        }
        _write_new(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _write_new(output / "input-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _write_new(output / "version-groups.json", json.dumps(version_groups, ensure_ascii=False, indent=2) + "\n")
        _write_new(output / "acquisition-report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        _write_new(output / "source-LICENSE.txt", f"BFDB dataset record: {ZENODO_RECORD_URL}\nABC archive: {ZENODO_ABC_URL}\nDeclared dataset license: {LICENSE}\nLicense URL: {LICENSE_URL}\n\nThe dataset license is preserved as candidate metadata. It does not automatically clear underlying tunes or bundled redistribution.\n")
        _write_new(output / "README.md", f"# BFDB candidate intake ({len(selected)} entries)\n\nSource: `{ZENODO_RECORD_URL}`\nConversion: music21 {music21_version}\nSelected: `{len(selected)}`; conversion/validation failures retained in `acquisition-report.json`.\n\nAll entries remain `candidate-unverified`, `musicReview=not-reviewed`, `gameReview=not-tested`, and `RedistributionVerified=false`.\n")
        return {"manifest": manifest, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--exclude-manifest", action="append", default=[])
    parser.add_argument("--music21-path", type=Path, default=ROOT.parent / ".tools" / "python-packages" / "music21-9.9.2")
    args = parser.parse_args(argv)
    try:
        result = acquire_batch(args.source_root, args.output, limit=args.limit, offset=args.offset, exclude_manifests=args.exclude_manifest, music21_path=args.music21_path)
    except (IntakeError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"FAIL BFDB intake: {exc}", flush=True)
        return 2
    print(f"PASS BFDB intake: selected={result['report']['selectedCount']} output={args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())