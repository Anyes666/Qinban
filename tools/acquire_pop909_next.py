"""Acquire the next POP909 batch from the pinned local archive.

This is an offline, additive intake step. It never modifies Songs/dist/UserData and
never treats a title-only row as a score. Explicit editions may share a WorkId but
must retain a distinct EditionId and a visible VersionLabel.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from acquire_pop909_100 import COMMIT, REPO
from discover_pop_metadata import parse_index
from smf_reference import parse_smf
from update_builtin_library import read_catalog
from acquire_pop909_200 import work_key

ROOT = Path(__file__).resolve().parents[1]
OLD_INTAKE = ROOT / "catalog-intake" / "pop100-2026-10-06"
SOURCE_SONGS = ROOT / "Songs"
ARCHIVE_NAME = "source-archive.zip"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def title_version_label(title: str, same_work_as_existing: bool) -> tuple[str, str]:
    """Return (display label, evidence basis), never infer a version from the artist alone."""
    value = unicodedata.normalize("NFKC", title).strip()
    explicit = []
    if re.search(r"DJ", value, re.I):
        explicit.append("DJ版")
    for marker, label in (("原版", "原版"), ("新版", "新版"), ("消音版", "消音版")):
        if marker in value:
            explicit.append(label)
    for marker in ("万万没想到", "重返20岁", "步步惊心"):
        if marker in value:
            explicit.append(f"影视/主题版本：{marker}")
    if explicit:
        return "、".join(dict.fromkeys(explicit)), "source-title-explicit-marker"
    if same_work_as_existing:
        return "POP909来源演唱/编配版", "same-normalized-work-key-as-existing"
    return "", "unique-normalized-work-key"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new intake directory under catalog-intake")
    parser.add_argument("--limit", type=int, default=0, help="stable source-order cap; 0 means all accepted remaining rows")
    args = parser.parse_args()
    output = args.output.resolve()
    intake_root = (ROOT / "catalog-intake").resolve()
    if not output.is_relative_to(intake_root) or output.exists():
        raise ValueError("Use a NEW intake directory inside catalog-intake")
    if args.limit < 0:
        raise ValueError("--limit cannot be negative")

    old_manifest = json.loads((OLD_INTAKE / "manifest.json").read_text(encoding="utf-8"))
    old_report = json.loads((OLD_INTAKE / "acquisition-report.json").read_text(encoding="utf-8"))
    archive_path = OLD_INTAKE / ARCHIVE_NAME
    if old_manifest["sourceCommit"] != COMMIT or sha(archive_path.read_bytes()) != old_report["sourceArchiveSha256"]:
        raise ValueError("Pinned source archive changed")
    tree = json.loads((OLD_INTAKE / "source-tree.json").read_text(encoding="utf-8"))
    if tree.get("truncated"):
        raise ValueError("Pinned source tree is truncated")
    source_blobs = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}

    catalog = read_catalog(SOURCE_SONGS)
    existing_ids: set[str] = set()
    used_source_hashes: set[str] = set()
    existing_work_by_key: dict[str, str] = {}
    existing_title_by_key: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for _, (relative, _, metadata) in catalog.items():
        match = re.fullmatch(r"pop909-(\d{3})\.json", relative)
        if match:
            existing_ids.add(match.group(1))
        provenance = metadata.get("provenance", {})
        source_hash = str(provenance.get("sourceSha256", "")).upper()
        if source_hash:
            used_source_hashes.add(source_hash)
        key = work_key(str(metadata.get("title", "")))
        work_id = str(provenance.get("workId", ""))
        if key and work_id and key not in existing_work_by_key:
            existing_work_by_key[key] = work_id
        existing_title_by_key[key].append({
            "title": str(metadata.get("title", "")),
            "artist": str(provenance.get("artist", "")),
            "workId": work_id,
        })
        for alias in provenance.get("aliases", []) or []:
            alias_key = work_key(str(alias))
            if alias_key and work_id and alias_key not in existing_work_by_key:
                existing_work_by_key[alias_key] = work_id

    rows = parse_index((OLD_INTAKE / "index.xlsx").read_bytes())
    output.mkdir(parents=False)
    (output / "midi").mkdir()
    (output / "references").mkdir()
    selected: list[dict] = []
    rejected: list[dict] = []
    version_rows: list[dict] = []
    selected_hashes: set[str] = set()
    new_work_by_key: dict[str, str] = {}
    new_id_by_key: dict[str, str] = {}
    prefix = f"POP909-Dataset-{COMMIT}/"

    with zipfile.ZipFile(archive_path) as archive:
        for row in rows:
            sid = row["sourceIndexId"]
            if sid in existing_ids:
                continue
            if args.limit and len(selected) >= args.limit:
                break
            title = str(row["title"]).strip()
            artists = [str(value).strip() for value in row.get("artists", []) if str(value).strip()]
            if not title or not artists:
                rejected.append({"id": sid, "title": title, "reason": "missing indexed title or artist"})
                continue
            artist = artists[0]
            key = work_key(title)
            same_existing = key in existing_work_by_key
            version_label, version_basis = title_version_label(title, same_existing)
            work_id = existing_work_by_key.get(key) or new_work_by_key.get(key) or f"pop909-work:{key}"
            if key not in existing_work_by_key and key not in new_work_by_key:
                new_work_by_key[key] = work_id
                new_id_by_key[key] = sid
            relative_source = f"POP909/{sid}/{sid}.mid"
            try:
                info = archive.getinfo(prefix + relative_source)
                if info.file_size > 16 * 1024 * 1024:
                    raise ValueError("source size over 16MiB")
                data = archive.read(info)
                source_hash = sha(data)
                if source_hash in used_source_hashes or source_hash in selected_hashes:
                    raise ValueError("source MIDI bytes duplicate an existing/selected edition")
                if git_blob(data) != source_blobs.get(relative_source):
                    raise ValueError("source Git blob mismatch")
                reference = parse_smf(data)
                if reference["durationKinds"] < 2:
                    raise ValueError("source has no meaningful duration variety")
                if not 90_000 <= reference["lengthMs"] <= 1_800_000:
                    raise ValueError("source outside 90-second to 30-minute parser budget")
                if not 1 <= len(reference["notes"]) <= 100_000:
                    raise ValueError("source note count outside budget")
                if not any(note["track"] == 1 and not note["percussion"] for note in reference["notes"]):
                    raise ValueError("source has no non-percussion track 1 melody")
            except Exception as error:
                rejected.append({"id": sid, "title": title, "artist": artist, "reason": repr(error)})
                continue

            midi_path = output / "midi" / f"{sid}.mid"
            reference_path = output / "references" / f"{sid}.json"
            with midi_path.open("xb") as stream:
                stream.write(data)
            write_new(reference_path, reference)
            edition_id = f"pop909:{COMMIT}:{sid}"
            item = {
                "id": sid,
                "title": title,
                "artist": artist,
                "artists": artists,
                "workId": work_id,
                "editionId": edition_id,
                "versionLabel": version_label,
                "versionBasis": version_basis,
                "midiPath": str(midi_path),
                "referencePath": str(reference_path),
                "sourceUrl": f"https://github.com/{REPO}/blob/{COMMIT}/{relative_source}",
                "metadataSource": f"https://github.com/{REPO}/blob/{COMMIT}/POP909/index.xlsx",
                "sourceSha256": source_hash,
                "githubBlobSha": source_blobs[relative_source],
                "languageTags": [],
                "languageStatus": "not-stated-by-source",
                "album": "",
                "durationMs": reference["lengthMs"],
                "notes": len(reference["notes"]),
                "tempoChanges": reference["tempoChanges"],
                "durationKinds": reference["durationKinds"],
                "completeness": "unknown",
                "musicReview": "not-reviewed",
                "gameReview": "not-tested",
                "redistributionVerified": False,
            }
            selected.append(item)
            selected_hashes.add(source_hash)
            if version_label or same_existing:
                version_rows.append({
                    "id": sid,
                    "title": title,
                    "artist": artist,
                    "workId": work_id,
                    "editionId": edition_id,
                    "versionLabel": version_label or "POP909来源演唱/编配版",
                    "versionBasis": version_basis,
                    "relatedExistingOrNewTitle": existing_title_by_key.get(key, [])
                    or [{"id": new_id_by_key.get(key, sid), "workId": work_id}],
                })
            print(f"SELECT {len(selected):03d} {sid} {title} - {artist} [{version_label or 'standard'}]", flush=True)

    if not selected:
        raise ValueError("No valid remaining source editions")
    manifest = {
        "sourceCommit": COMMIT,
        "retrievedAtUtc": now(),
        "provider": "POP909",
        "batchKind": "remaining-pinned-source-editions",
        "songs": selected,
    }
    write_new(output / "manifest.json", manifest)
    report = {
        "status": "PASS_LOCAL_PINNED_ARCHIVE_REMAINING_BATCH",
        "sourceArchiveSha256": old_report["sourceArchiveSha256"],
        "sourceArchive": str(archive_path),
        "sourceIndexSha256": sha((OLD_INTAKE / "index.xlsx").read_bytes()),
        "existingCatalogEntries": len(catalog),
        "existingPop909Ids": len(existing_ids),
        "remainingIndexRows": len(rows) - len(existing_ids),
        "selectedEditions": len(selected),
        "rejectedRows": len(rejected),
        "versionRows": len(version_rows),
        "distinctSourceHashes": len({item["sourceSha256"] for item in selected}),
        "distinctWorkIdsInBatch": len({item["workId"] for item in selected}),
        "explicitVersionLabels": collections.Counter(item["versionLabel"] for item in selected if item["versionLabel"]),
        "rejected": rejected,
        "versionRowsDetail": version_rows,
        "limitations": [
            "Version grouping uses conservative normalized title keys and explicit source-title markers; it is not a global work-identity certification.",
            "POP909 repository MIT does not certify underlying commercial-song redistribution; this remains a local personal-library intake.",
            "Source timing comparison is not human music review, original-audio matching, or real-game validation.",
            "Language, album and recording edition remain unknown unless stated by the pinned source index.",
        ],
    }
    write_new(output / "acquisition-report.json", report)
    shutil.copyfile(OLD_INTAKE / "source-LICENSE.txt", output / "source-LICENSE.txt")
    shutil.copyfile(OLD_INTAKE / "source-README.md", output / "source-README.md")
    write_new(output / "version-groups.json", {"workIds": version_rows, "policy": "same WorkId, distinct EditionId; explicit VersionLabel required when source title states an edition"})
    print(f"PASS next POP909 intake: {len(selected)} editions; {len(version_rows)} version-labelled/grouped; {len(rejected)} rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
