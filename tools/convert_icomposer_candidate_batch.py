"""Convert iComposer research references into an isolated generic PopBatch intake.

This adapter deliberately produces research candidates only. It preserves the
source-relative durations as milliseconds using a neutral 60-BPM anchor because
iComposer files do not provide a tempo map. It never writes Songs, dist, EXE or
UserData and never claims music/game/redistribution acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from typing import Any

SCHEMA_VERSION = "icomposer-popbatch-adapter/v1"
REPO = "https://github.com/hhpslily/iComposer"
LICENSE = "dataset-license-not-stated"
RIGHTS_STATUS = "candidate-unverified"
VERSION_LABEL = "iComposer research transcription candidate"
BATCH_KIND = "icomposer-structured-candidate-intake"
BPM_ANCHOR = 60
TICKS_PER_QUARTER = 480
HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"


def _vlq(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative MIDI delta")
    buffer = value & 0x7F
    encoded = bytearray()
    while value > 0x7F:
        value >>= 7
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
    while True:
        encoded.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(encoded)


def _midi_track(notes: list[dict[str, Any]]) -> bytes:
    events: list[tuple[int, int, bytes]] = []
    tempo = int(60_000_000 / BPM_ANCHOR)
    events.append((0, -3, b"\xff\x51\x03" + tempo.to_bytes(3, "big")))
    track_name = b"MELODY"
    events.append((0, -2, b"\xff\x03" + bytes([len(track_name)]) + track_name))
    events.append((0, -1, b"\xc0\x00"))
    for note in notes:
        pitch = int(note["pitch"])
        start_tick = int(round(float(note["startMs"]) / 1000.0 * TICKS_PER_QUARTER))
        end_tick = int(round((float(note["startMs"]) + float(note["durationMs"])) / 1000.0 * TICKS_PER_QUARTER))
        if not 0 <= pitch <= 127 or end_tick <= start_tick:
            raise ValueError("invalid converted note")
        velocity = max(1, min(127, int(note.get("velocity", 88))))
        events.append((start_tick, 1, bytes([0x90, pitch, velocity])))
        events.append((end_tick, 0, bytes([0x80, pitch, 0])))
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    data = bytearray()
    cursor = 0
    for tick, _, payload in events:
        data.extend(_vlq(tick - cursor))
        data.extend(payload)
        cursor = tick
    data.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + len(data).to_bytes(4, "big") + bytes(data)


def _midi_bytes(notes: list[dict[str, Any]]) -> bytes:
    track = _midi_track(notes)
    header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + TICKS_PER_QUARTER.to_bytes(2, "big")
    return header + track


def _source_name(source_url: str, title: str) -> str:
    name = unquote(source_url.rsplit("/", 1)[-1])
    return name if name.endswith(".txt") else title + ".txt"


def _github_blob_url(commit: str, directory: str, name: str) -> str:
    return f"{REPO}/blob/{commit}/{directory}/{quote(name)}"


def _entry_notes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for event in entry.get("Notes", []):
        start_ms = round(float(event["start"]) * 1000.0, 3)
        duration_ms = round(float(event["duration"]) * 1000.0, 3)
        if not math.isfinite(start_ms) or not math.isfinite(duration_ms) or duration_ms <= 0:
            raise ValueError("source duration is not finite and positive")
        for pitch in sorted({int(value) for value in event.get("pitches", [])}):
            flattened.append({
                "pitch": pitch,
                "startMs": start_ms,
                "durationMs": duration_ms,
                "track": 0,
                "velocity": 88,
                "percussion": False,
            })
    flattened.sort(key=lambda note: (note["startMs"], note["pitch"], note["durationMs"]))
    if not flattened:
        raise ValueError("candidate contains no notes")
    return flattened


def _write_new(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")


def convert_batch(
    references_path: Path,
    output_dir: Path,
    *,
    source_commit: str,
    retrieved_at: str,
    limit: int | None = None,
    archive_sha256: str = "",
    write: bool = True,
) -> dict[str, Any]:
    if not HEX64.fullmatch(archive_sha256) and archive_sha256:
        raise ValueError("archive_sha256 must be 64 hex characters")
    if not references_path.is_file():
        raise FileNotFoundError(references_path)
    references_hash = sha256_file(references_path)
    payload = json.loads(references_path.read_text(encoding="utf-8"))
    entries = list(payload.get("entries", []))
    entries.sort(key=lambda item: (str(item.get("Title", "")).casefold(), str(item.get("EditionId", ""))))
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        entries = entries[:limit]
    if not entries:
        raise ValueError("empty iComposer conversion batch")
    if write and output_dir.exists():
        raise FileExistsError(output_dir)
    midi_dir = output_dir / "midi"
    reference_dir = output_dir / "references"
    if write:
        midi_dir.mkdir(parents=True)
        reference_dir.mkdir(parents=True)
    songs: list[dict[str, Any]] = []
    converted: list[dict[str, Any]] = []
    for item in entries:
        notes = _entry_notes(item)
        source = item.get("Source", {})
        source_hash = str(source.get("noteDownloadSha256") or item.get("SourceSha256") or "").upper()
        if not HEX64.fullmatch(source_hash):
            raise ValueError(f"invalid source sha256 for {item.get('Title')}")
        source_name = _source_name(str(item.get("SourceUrl", "")), str(item.get("WorkId", "candidate")))
        title = str(item.get("Title") or Path(source_name).stem).strip()
        if not title:
            raise ValueError("candidate title is empty")
        stable_id = f"icomposer-{source_hash[:16].lower()}"
        midi_path = (midi_dir / f"{stable_id}.mid").resolve()
        reference_path = (reference_dir / f"{stable_id}.json").resolve()
        ref_notes = [
            {key: note[key] for key in (
                "pitch", "startMs", "durationMs", "track", "velocity", "percussion"
            )}
            for note in notes
        ]
        length_ms = round(max(float(n["startMs"]) + float(n["durationMs"]) for n in notes), 3)
        source_url = _github_blob_url(source_commit, "dataset/lyrics_note", source_name)
        duration_url = _github_blob_url(source_commit, "dataset/lyrics_duration", source_name)
        tags = ["??????", "????", "???????", "?????"]
        song = {
            "Id": stable_id,
            "Title": title,
            "Artist": "???????",
            "Artists": ["???????"],
            "MidiPath": str(midi_path),
            "ReferencePath": str(reference_path),
            "SourceUrl": source_url,
            "SourceSha256": source_hash,
            "NotationSha256": "",
            "LanguageTags": [],
            "Provider": "iComposer",
            "SourceCommit": source_commit,
            "SourceRecord": REPO,
            "BatchKind": BATCH_KIND,
            "Author": "iComposer dataset / source transcription",
            "Category": "?????? ? iComposer???? ? ???????",
            "Description": "?????????????????? tempo map????????????????????",
            "IdPattern": "icomposer-<source-sha-prefix>",
            "SmartInterludes": True,
            "WorkId": item.get("WorkId", stable_id),
            "EditionId": item.get("EditionId", stable_id),
            "VersionLabel": VERSION_LABEL,
            "License": LICENSE,
            "LicenseUrl": "",
            "RightsStatus": RIGHTS_STATUS,
            "RightsNote": "???????? LICENSE????????????????????????",
            "Album": "",
            "Aliases": [title],
            "Tags": tags,
            "Completeness": "source-relative-melody",
            "MusicReview": "not-reviewed",
            "GameReview": "not-tested",
            "RedistributionVerified": False,
        }
        midi_data = _midi_bytes(notes)
        midi_hash = sha256_bytes(midi_data)
        # PopBatchTool compares reference.sourceSha256 with the actual MIDI
        # artifact hash (NotationSha256), while SourceSha256 remains the
        # original iComposer note-file hash. Keep those evidence classes
        # separate and make the required timing fields explicit.
        reference = {
            "notes": ref_notes,
            "lengthMs": length_ms,
            "bpm": BPM_ANCHOR,
            "tempoChanges": 1,
            "reference": "iComposer source-relative durations mapped at a neutral 60-BPM anchor",
            "sourceSha256": midi_hash,
            "synthetic": False,
        }
        song["NotationSha256"] = midi_hash
        if write:
            _write_new(midi_path, midi_data)
            _write_new(reference_path, canonical_json(reference))
        songs.append(song)
        converted.append({"id": stable_id, "title": title, "noteCount": len(notes), "lengthMs": length_ms, "sourceUrl": source_url, "durationUrl": duration_url})
    manifest = {
        "Songs": songs,
        "SourceCommit": source_commit,
        "SourceRecord": REPO,
        "RetrievedAtUtc": retrieved_at,
        "Provider": "iComposer",
        "BatchKind": BATCH_KIND,
        "SourceUrl": REPO,
        "License": LICENSE,
        "LicenseUrl": "",
        "RightsStatus": RIGHTS_STATUS,
        "RightsNote": "Research candidate only; no redistribution or production builtin acceptance.",
        "RedistributionVerified": False,
        "Author": "iComposer dataset / source transcription",
        "Category": "?????? ? iComposer????",
        "Description": "? iComposer ??/??????? MIDI + reference?? tempo ?????? 60-BPM ???????????????",
        "IdPattern": "icomposer-<source-sha-prefix>",
        "SmartInterludesDefault": True,
    }
    audit = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceCommit": source_commit,
        "sourceRecord": REPO,
        "referencesPath": str(references_path.resolve()),
        "referencesSha256": references_hash,
        "archiveSha256": archive_sha256,
        "retrievedAtUtc": retrieved_at,
        "countRequested": limit if limit is not None else len(entries),
        "countConverted": len(songs),
        "sourceDurationMapping": "1 source duration unit = 1000ms; no tempo map supplied; MIDI tempo anchor=60 BPM",
        "license": LICENSE,
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": False,
        "musicReview": "not-reviewed",
        "gameReview": "not-tested",
        "productionBuiltin": False,
        "sourceBoundary": "Conversion and numerical structure evidence only; not rights, human music or game acceptance.",
        "converted": converted,
    }
    result = {"manifest": manifest, "audit": audit, "count": len(songs), "outputDir": str(output_dir.resolve())}
    if write:
        _write_new(output_dir / "manifest.json", canonical_json(manifest))
        _write_new(output_dir / "source-audit.json", canonical_json(audit))
        readme = ("# iComposer research candidate PopBatch\n\n"
                  "This is an isolated candidate conversion, not a production builtin batch.\n"
                  "The source has no verified dataset license, no per-song singer/version audit, and no tempo map.\n"
                  "Durations are mapped as source-relative seconds and the MIDI uses a neutral 60-BPM anchor.\n"
                  "Do not install or redistribute until rights and human musical review are complete.\n")
        _write_new(output_dir / "README.md", readme)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert iComposer research references into isolated MIDI candidates")
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--retrieved-at", default="2026-10-07T00:00:00Z")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--archive-sha256", default="")
    args = parser.parse_args(argv)
    try:
        result = convert_batch(args.references, args.output, source_commit=args.source_commit, retrieved_at=args.retrieved_at, limit=args.limit, archive_sha256=args.archive_sha256, write=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "count": result["count"], "outputDir": result["outputDir"], "productionBuiltin": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
