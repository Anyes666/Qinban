"""Acquire the CC-BY Cantopop corpus as a generic structured-score batch.

The source is Humdrum **kern, not MIDI.  This intake converts only the melody
spine into a deterministic Standard MIDI file, writes an independent SMF
reference, and creates the manifest consumed by PopBatchTool.  It never writes
Songs, catalog.db, the EXE, UserData, or sends input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "catalog-intake" / "cantopop-2026-10-07" / "source"
DEFAULT_OUTPUT = ROOT / "catalog-intake" / "cantopop-2026-10-07" / "batch"
PYTHON_PACKAGES = ROOT.parent / ".tools" / "python-packages" / "music21-9.9.2"
TOOLS = ROOT / "tools"
if str(PYTHON_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PYTHON_PACKAGES))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from music21 import converter  # noqa: E402
from smf_reference import parse_smf  # noqa: E402

SOURCE_REPO = "https://github.com/jasonleeubc/Cantopop-corpus"
SOURCE_COMMIT = ""
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def vlq(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative MIDI delta")
    buffer = value & 0x7F
    result = bytearray()
    while value := value >> 7:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
    while True:
        result.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(result)


def track_chunk(payload: bytes) -> bytes:
    return b"MTrk" + struct.pack(">I", len(payload)) + payload


def meta_event(delta: int, kind: int, payload: bytes) -> bytes:
    return vlq(delta) + bytes((0xFF, kind)) + vlq(len(payload)) + payload


def text_meta(delta: int, kind: int, text: str) -> bytes:
    return meta_event(delta, kind, text.encode("utf-8"))


def parse_int(text: str) -> int:
    return int(text.strip())


def parse_csv(source: Path) -> dict[str, dict[str, str]]:
    path = source / "Cantopop corpus list_final.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        song_id = (row.get("ID") or "").strip()
        if not re.fullmatch(r"C\d{4}", song_id):
            raise ValueError(f"invalid Cantopop ID: {song_id!r}")
        if song_id in result:
            raise ValueError(f"duplicate Cantopop ID: {song_id}")
        if not (row.get("Song Title") or "").strip() or not (row.get("Singer") or "").strip():
            raise ValueError(f"missing title/singer: {song_id}")
        result[song_id] = {str(k): str(v or "").strip() for k, v in row.items()}
    if len(result) != 105:
        raise ValueError(f"expected 105 CSV rows, found {len(result)}")
    return result


def tempo_boundaries(score) -> list[tuple[float, float]]:
    boundaries = []
    for offset, _end, mark in score.metronomeMarkBoundaries():
        if mark is None or mark.number is None or not math.isfinite(float(mark.number)) or float(mark.number) <= 0:
            continue
        bpm = float(mark.number)
        if boundaries and abs(boundaries[-1][0] - float(offset)) < 1e-9:
            boundaries[-1] = (float(offset), bpm)
        else:
            boundaries.append((float(offset), bpm))
    if not boundaries:
        boundaries = [(0.0, 100.0)]
    if boundaries[0][0] > 1e-9:
        boundaries.insert(0, (0.0, boundaries[0][1]))
    return boundaries


def note_segments(score) -> tuple[list[tuple[float, float, int]], int]:
    notes = []
    skipped_grace = 0
    for element in score.flatten().notes:
        if not hasattr(element, "pitch"):
            continue
        pitch = int(element.pitch.midi)
        if not 0 <= pitch <= 127:
            raise ValueError(f"MIDI pitch out of range: {pitch}")
        start = float(element.offset)
        length = float(element.quarterLength)
        if not math.isfinite(start) or not math.isfinite(length) or start < 0:
            raise ValueError(f"invalid note timing: {start}, {length}")
        if length <= 0:
            # **kern grace notes have no metric duration. The native contract
            # rejects zero-length events, so omit them instead of inventing a
            # duration or shifting the melody.
            skipped_grace += 1
            continue
        notes.append((start, start + length, pitch, element.tie.type if element.tie else None))
    notes.sort(key=lambda value: (value[0], value[2], value[1]))
    # Merge only explicit ties for sustain fidelity. Untied repeated notes stay
    # separate attacks even when their pitch and onset are adjacent.
    merged: list[list[float | int]] = []
    by_pitch: dict[int, list[list[float | int]]] = defaultdict(list)
    for start, end, pitch, tie_type in notes:
        previous = by_pitch[pitch][-1] if by_pitch[pitch] else None
        if previous is not None and abs(float(previous[1]) - start) < 1e-8 and tie_type in {"continue", "stop"}:
            previous[1] = end
            continue
        item: list[float | int] = [start, end, pitch]
        by_pitch[pitch].append(item)
        merged.append(item)
    merged.sort(key=lambda value: (float(value[0]), int(value[2]), float(value[1])))
    return [(float(start), float(end), int(pitch)) for start, end, pitch in merged], skipped_grace


def choose_ppq(notes: list[tuple[float, float, int]], tempos: list[tuple[float, float]], highest: float) -> int:
    # Humdrum durations are normally simple fractions. Use a high fixed PPQ
    # and record the maximum quantisation error in the batch report.
    return 9600


def tick(value: float, ppq: int) -> int:
    return max(0, int(round(value * ppq)))


def write_midi(score, output: Path) -> dict[str, float | int | str]:
    notes, skipped_grace = note_segments(score)
    tempos = tempo_boundaries(score)
    highest = max([float(score.highestTime), *(end for _, end, _ in notes), 0.0])
    ppq = choose_ppq(notes, tempos, highest)
    note_events: list[tuple[int, int, int, int]] = []
    max_tick_error = 0.0
    for start, end, pitch in notes:
        st, et = tick(start, ppq), tick(end, ppq)
        if et <= st:
            et = st + 1
        max_tick_error = max(max_tick_error, abs(st / ppq - start), abs(et / ppq - end))
        note_events.append((st, 1, pitch, 90))
        note_events.append((et, 0, pitch, 90))
    # Note-off before note-on at the same tick avoids same-pitch overlap.
    note_events.sort(key=lambda value: (value[0], value[1], value[2]))
    tempo_events: list[tuple[int, int]] = []
    for offset, bpm in tempos:
        t = tick(offset, ppq)
        micros = max(1, int(round(60_000_000 / bpm)))
        if tempo_events and tempo_events[-1][0] == t:
            tempo_events[-1] = (t, micros)
        else:
            tempo_events.append((t, micros))
    tempo_track = bytearray()
    last = 0
    for t, micros in tempo_events:
        tempo_track += meta_event(t - last, 0x51, micros.to_bytes(3, "big"))
        last = t
    tempo_track += meta_event(0, 0x58, bytes((4, 2, 24, 8)))
    tempo_track += meta_event(0, 0x2F, b"")
    note_track = bytearray()
    note_track += text_meta(0, 0x03, "MELODY")
    last = 0
    for t, kind, pitch, velocity in note_events:
        note_track += vlq(t - last)
        note_track += bytes((0x90 if kind else 0x80, pitch, velocity if kind else 0))
        last = t
    end_tick = max(tick(highest, ppq), last)
    note_track += vlq(max(0, end_tick - last)) + bytes((0xFF, 0x2F, 0x00))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, ppq)
    output.write_bytes(header + track_chunk(bytes(tempo_track)) + track_chunk(bytes(note_track)))
    return {"notes": len(notes), "lengthQuarter": highest, "ppq": ppq, "maxQuantizationQuarter": max_tick_error, "tempoEvents": len(tempo_events), "skippedGraceNotes": skipped_grace}


def json_dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_commit(source: Path) -> str:
    manifest = source.parent / "retrieval-manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("commit"):
            return str(payload["commit"])
    return "main"


def build(args) -> int:
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise RuntimeError(f"source directory missing: {source}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    midi_dir, ref_dir = output / "midi", output / "references"
    midi_dir.mkdir(); ref_dir.mkdir()
    rows = parse_csv(source)
    ids = sorted(rows)
    if args.limit:
        ids = ids[: args.limit]
    commit = read_commit(source)
    title_counts = Counter(rows[song_id]["Song Title"] for song_id in ids)
    songs = []
    stats = []
    for song_id in ids:
        row = rows[song_id]
        krn = source / "Humdrum-files" / f"{song_id}.krn"
        if not krn.is_file():
            raise RuntimeError(f"missing Humdrum source: {krn}")
        score = converter.parse(str(krn), format="humdrum")
        midi_path = midi_dir / f"cantopop-{song_id.lower()}.mid"
        parse_stats = write_midi(score, midi_path)
        source_ref = parse_smf(midi_path.read_bytes())
        source_ref["SourceSha256"] = sha256_file(midi_path)
        source_ref["reference"] = "independent Python SMF parser over deterministic Humdrum conversion; no lyrics bundled"
        ref_path = ref_dir / f"cantopop-{song_id.lower()}.json"
        json_dump(ref_path, source_ref)
        krn_sha = sha256_file(krn)
        artist = row["Singer"]
        raw_title = row["Song Title"]
        duplicate_title = title_counts[raw_title] > 1
        title = raw_title if not duplicate_title else f"{raw_title} [{artist}, {row['Year']}]"
        aliases = [raw_title] if duplicate_title else []
        tag = ["中文流行", "粤语流行", "Cantopop", "humdrum", "CC-BY-4.0候选", f"humdrum-sha256:{krn_sha}"]
        if duplicate_title:
            tag.append("duplicate-title-disambiguated")
        if int(parse_stats["skippedGraceNotes"]) > 0:
            tag.append(f"zero-duration-grace-notes-omitted:{int(parse_stats['skippedGraceNotes'])}")
        songs.append({
            "id": f"cantopop-{song_id.lower()}",
            "title": title,
            "artist": artist,
            "artists": [artist],
            "midiPath": str(midi_path),
            "referencePath": str(ref_path),
            "sourceUrl": f"{SOURCE_REPO}/blob/{commit}/Humdrum-files/{song_id}.krn",
            "sourceSha256": sha256_file(krn),
            "notationSha256": sha256_file(midi_path),
            "languageTags": ["yue"],
            "provider": "CantopopCorpus",
            "sourceCommit": commit,
            "sourceRecord": f"Humdrum-files/{song_id}.krn sha256={krn_sha}",
            "batchKind": "cantopop-ccby4-2026-10-07-v2",
            "author": "Cantopop Corpus · Humdrum 转谱",
            "category": "粤语流行 · Cantopop · 待音乐审核",
            "description": "来源为 CC-BY-4.0 Cantopop corpus 的 **kern 单旋律转谱；不把歌词打入软件。语音/歌曲版权、音乐人工精校和原神内验收另行审计。",
            "idPattern": "^cantopop-[a-z0-9-]+$",
            "smartInterludes": True,
            "workId": f"cantopop-work:{song_id.lower()}",
            "editionId": f"cantopop-ccby4:{song_id.lower()}",
            "versionLabel": f"Cantopop corpus \u5355\u65cb\u5f8b\u8f6c\u5f55\u7248 \u00b7 {row['Year']}\u5e74" + (f" \u00b7 {artist}\u7248" if duplicate_title else ""),
            "license": "CC-BY-4.0",
            "licenseUrl": LICENSE_URL,
            "rightsStatus": "candidate-cc-by-4-0",
            "rightsNote": "仓库声明 CC-BY-4.0；底层歌曲/录音的独立权利未逐曲核验，不能宣称可公开商业再分发。",
            "album": "",
            "aliases": aliases,
            "tags": tag,
            "completeness": "unknown",
            "musicReview": "not-reviewed",
            "gameReview": "not-tested",
            "redistributionVerified": False,
        })
        stats.append({"id": song_id, "title": title, "artist": artist, "year": row["Year"], "krnSha256": krn_sha, "midiSha256": sha256_file(midi_path), "referenceSha256": sha256_file(ref_path), **parse_stats, "smfNotes": len(source_ref["notes"]), "smfLengthMs": source_ref["lengthMs"], "smfBpm": source_ref["bpm"], "smfTempoChanges": source_ref["tempoChanges"]})
    manifest = {
        "provider": "CantopopCorpus",
        "batchKind": "cantopop-ccby4-2026-10-07-v2",
        "sourceCommit": commit,
        "sourceRecord": "Cantopop corpus list_final.csv + Humdrum-files/*.krn",
        "retrievedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceUrl": SOURCE_REPO,
        "license": "CC-BY-4.0",
        "licenseUrl": LICENSE_URL,
        "rightsStatus": "candidate-cc-by-4-0",
        "rightsNote": "仓库声明 CC-BY-4.0；底层歌曲/录音的独立权利未逐曲核验。",
        "redistributionVerified": False,
        "author": "Cantopop Corpus · Humdrum 转谱",
        "category": "粤语流行 · Cantopop · 待音乐审核",
        "description": "105 首 2000–2020 粤语流行曲的 **kern 单旋律转录，转换为 deterministic MIDI；无歌词打包。",
        "smartInterludesDefault": True,
        "songs": songs,
    }
    json_dump(output / "manifest.json", manifest)
    json_dump(output / "conversion-report.json", {"status": "PASS_LOCAL_HUMDRUM_TO_DETERMINISTIC_MIDI", "source": str(source), "output": str(output), "songCount": len(songs), "songs": stats, "nativeKeySendAttempts": 0, "productionSongsWritten": 0, "rightsStatus": "candidate-cc-by-4-0", "redistributionVerified": False})
    (output / "README.md").write_text("# Cantopop CC-BY structured batch\n\nThis is intake/build input only. It is not installed into Songs by this script. The source repository declares CC-BY-4.0; underlying song/recording rights remain unverified. No lyrics are bundled.\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(output / "manifest.json"), "songs": len(songs), "midi": len(list(midi_dir.glob("*.mid"))), "references": len(list(ref_dir.glob("*.json")))}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    return build(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
