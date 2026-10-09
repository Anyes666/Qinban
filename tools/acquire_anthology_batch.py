"""Build an auditable Chinese folk MIDI intake batch from the pinned archive.

This script only extracts a deterministic, metadata-first candidate batch into
catalog-intake. It never writes Songs, catalog.db, QinBan.exe, UserData, or
sends keyboard/game input. The repository has no dataset license file, so every
entry remains candidate-unverified and redistributionVerified=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT.parent / ".tools" / "sources" / "anthology-chinese-folk-20261007.zip"
DEFAULT_OUTPUT = ROOT / "catalog-intake" / "anthology-chinese-folk-20261007" / "batch-200-melody-only"
COMMIT = "6e41177295be9380dd447877da9aa517a9911c76"
REPO = "https://github.com/m-july/Anthology-of-Chinese-Folk-Songs-v251103"
BLOB_BASE = REPO + "/blob/" + COMMIT + "/"
ROOT_IN_ARCHIVE = "Anthology-of-Chinese-Folk-Songs-v251103-main/"
VOLUMES = ("hainan", "hebei1", "hebei2", "henan", "jilin", "shanghai", "sichuan1", "tianjin")
PER_VOLUME = 25
SHA_RE = re.compile(r"^[0-9A-F]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def safe_token(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    text = re.sub(r"[^0-9A-Za-z_-]+", "-", text).strip("-")
    return text or "unknown"


def filename_parts(name: str) -> tuple[str, str]:
    base = Path(name).stem
    match = re.match(r"^(\d+)[_-](.*)$", base)
    if match:
        return match.group(1), match.group(2).strip()
    return "", base.strip()


def normalized_work(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = re.sub(r"[\s\-_·•，。、《》()（）\[\]【】]+", "", text)
    return text or "unknown"


def write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.write_text(text, encoding="utf-8", newline="\n")


def build(archive: Path, output: Path, per_volume: int = PER_VOLUME) -> dict:
    if output.exists():
        raise FileExistsError(f"output must be new: {output}")
    if not archive.is_file():
        raise FileNotFoundError(archive)
    archive_hash = sha256_file(archive)
    output.mkdir(parents=True)
    (output / "midi").mkdir()
    (output / "references").mkdir()
    selected: list[dict] = []
    rejected: list[dict] = []
    seen_source: set[str] = set()
    seen_edition: set[str] = set()
    seen_work: Counter[str] = Counter()
    with zipfile.ZipFile(archive) as z:
        infos = {
            i.filename: i for i in z.infolist()
            if i.filename.lower().endswith(".mid") and "/melody-only/" in i.filename
        }
        for volume in VOLUMES:
            prefix = ROOT_IN_ARCHIVE + "melody-only/" + volume + "/"
            names = sorted(n for n in infos if n.startswith(prefix))
            accepted_for_volume = 0
            for name in names:
                if accepted_for_volume >= per_volume:
                    break
                data = z.read(infos[name])
                try:
                    # Import lazily so the intake remains a simple deterministic script.
                    from smf_reference import parse_smf
                    reference = parse_smf(data)
                    if not reference.get("notes"):
                        raise ValueError("empty note list")
                except Exception as exc:  # retained as explicit reject evidence
                    rejected.append({"archivePath": name, "volume": volume, "error": str(exc)})
                    continue
                source_hash = sha256_bytes(data)
                if source_hash in seen_source:
                    rejected.append({"archivePath": name, "volume": volume, "error": "duplicate source SHA256"})
                    continue
                number, raw_title = filename_parts(Path(name).name)
                title = raw_title or Path(name).stem
                ordinal = number or f"{accepted_for_volume + 1:04d}"
                stem = safe_token(f"anthology-{volume}-{ordinal}")
                edition = f"anthology:csfs:{volume}:{ordinal}:{source_hash[:12]}"
                if edition in seen_edition:
                    rejected.append({"archivePath": name, "volume": volume, "error": "duplicate edition id"})
                    continue
                work_key = normalized_work(title)
                work_id = f"anthology-work:{work_key}"
                seen_source.add(source_hash)
                seen_edition.add(edition)
                seen_work[work_id] += 1
                midi_path = output / "midi" / f"{stem}.mid"
                ref_path = output / "references" / f"{stem}.json"
                midi_path.write_bytes(data)
                write_new(ref_path, json.dumps(reference, ensure_ascii=False, indent=2) + "\n")
                archive_rel = name[len(ROOT_IN_ARCHIVE):]
                selected.append({
                    "Id": stem,
                    "Title": title,
                    "Artist": "民歌/来源未标注",
                    "Artists": ["民歌/来源未标注"],
                    "MidiPath": str(midi_path.resolve()),
                    "ReferencePath": str(ref_path.resolve()),
                    "SourceUrl": BLOB_BASE + quote(archive_rel, safe="/-_.~"),
                    "SourceSha256": source_hash,
                    "LanguageTags": ["zh"],
                    "Provider": "AnthologyOfChineseFolkSongs",
                    "SourceCommit": COMMIT,
                    "SourceRecord": REPO,
                    "BatchKind": "melody-only-metadata-first-candidate-intake",
                    "Author": "Anthology OMR dataset / source transcription",
                    "Category": f"中文民歌 · {volume} · 待权利审核",
                    "Description": "Pinned-repository MIDI candidate; source title is retained, singer/artist was not supplied.",
                    "IdPattern": "anthology-<volume>-<ordinal>",
                    "SmartInterludes": True,
                    "WorkId": work_id,
                    "EditionId": edition,
                    "VersionLabel": f"Anthology · {volume} · {number or '无编号'} · 旋律版",
                    "License": "dataset-license-not-stated",
                    "LicenseUrl": "",
                    "RightsStatus": "candidate-unverified",
                    "RightsNote": "Repository contains derived MIDI/MusicXML but no dataset license file; original anthology scans are copyrighted per README; underlying works and redistribution scope remain unverified.",
                    "Album": "Anthology of Chinese Folk Songs",
                    "Aliases": [],
                    "Tags": ["中文歌曲", "中文民歌", "结构化谱", "candidate", "版权待核验", f"卷-{volume}"],
                    "Completeness": "source-midi",
                    "MusicReview": "not-reviewed",
                    "GameReview": "not-tested",
                    "RedistributionVerified": False,
                    "ReferenceStats": {k: reference[k] for k in ("lengthMs", "bpm", "tempoChanges", "durationKinds")},
                    "ArchivePath": name,
                })
                accepted_for_volume += 1
        if len(selected) != per_volume * len(VOLUMES):
            raise RuntimeError(f"selected {len(selected)} entries, expected {per_volume * len(VOLUMES)}")
    # Version labels must be distinct for duplicated work IDs.
    by_work: dict[str, list[dict]] = {}
    for s in selected:
        by_work.setdefault(s["WorkId"], []).append(s)
    for group in by_work.values():
        labels = [s["VersionLabel"] for s in group]
        if len(labels) != len(set(labels)):
            raise RuntimeError("duplicate version label within work")
    manifest = {
        "Songs": [{k: v for k, v in s.items() if k not in ("ReferenceStats", "ArchivePath")} for s in selected],
        "SourceCommit": COMMIT,
        "SourceRecord": REPO,
        "RetrievedAtUtc": datetime.now(timezone.utc).isoformat(),
        "Provider": "AnthologyOfChineseFolkSongs",
        "BatchKind": "melody-only-metadata-first-candidate-intake",
        "SourceUrl": REPO,
        "License": "dataset-license-not-stated",
        "LicenseUrl": "",
        "RightsStatus": "candidate-unverified",
        "RightsNote": "No dataset license file was found in the pinned repository; original scans are copyrighted per README; no redistribution clearance is asserted.",
        "RedistributionVerified": False,
        "Author": "Anthology OMR dataset / source transcription",
        "Category": "中文民歌 · 结构化 MIDI 候选",
        "Description": "Deterministic melody-only candidate batch from a pinned repository archive; not music/game/rights reviewed.",
        "IdPattern": "anthology-<volume>-<ordinal>",
        "SmartInterludesDefault": True,
    }
    write_new(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_new(output / "source-audit.json", json.dumps({
        "archive": str(archive.resolve()),
        "archiveSha256": archive_hash,
        "repository": REPO,
        "commit": COMMIT,
        "retrievalMethod": "codeload-zip",
        "sourceRootInArchive": ROOT_IN_ARCHIVE,
        "selectedCount": len(selected),
        "selectedPerVolume": per_volume,
        "volumeCounts": Counter(Path(s["ArchivePath"]).parts[-2] for s in selected),
        "uniqueSourceSha256": len({s["SourceSha256"] for s in selected}),
        "uniqueWorkIds": len({s["WorkId"] for s in selected}),
        "versionedWorkIds": {k: len(v) for k, v in by_work.items() if len(v) > 1},
        "rejectedDuringStructuralParse": len(rejected),
        "rejectedExamples": rejected[:50],
        "licenseFinding": "No dataset license file in repository; README says original scanned images are copyrighted.",
        "rightsStatus": "candidate-unverified",
        "redistributionVerified": False,
        "musicReview": "not-reviewed",
        "gameReview": "not-tested",
        "nativeInputAttempts": 0,
        "limitations": [
            "This batch is Chinese folk repertoire, not a platform-hot Chinese-pop ranking.",
            "Titles are source filenames; singer/artist metadata was not supplied and is explicitly marked unknown.",
            "The repository has no dataset license file; do not present this batch as cleared for public redistribution.",
            "MIDI/reference parsing proves structural timing only, not human listening or game acceptance.",
        ],
    }, ensure_ascii=False, indent=2) + "\n")
    write_new(output / "README.md", """# Chinese folk structured-score candidate batch\n\nThis is a deterministic 200-entry melody-only intake from the pinned Anthology of Chinese Folk Songs repository archive. It is isolated from `Songs`, `catalog.db`, the EXE, UserData, and real game input.\n\nAll entries remain `candidate-unverified`, `musicReview=not-reviewed`, `gameReview=not-tested`, and `redistributionVerified=false`. The repository contains no dataset license file; the source README notes that original scans are copyrighted. This batch must not be described as rights-cleared or platform-hot pop coverage.\n\nStructural evidence is provided by the independent SMF parser and by the PopBatchTool build report.\n""")
    return {"output": str(output), "selected": len(selected), "rejected": len(rejected), "archiveSha256": archive_hash}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--per-volume", type=int, default=PER_VOLUME)
    args = parser.parse_args()
    result = build(args.archive, args.output, args.per_volume)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
