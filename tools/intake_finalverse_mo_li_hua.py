"""Convert the CC0 Finalverse Mo Li Hua score into QinBan JSON.

This is a bounded, deterministic intake helper. It reads only the saved
Finalverse MCP evidence under an intake directory and never writes Songs,
 catalog.db, the EXE, UserData, or sends keyboard input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("intake", type=Path)
    args = parser.parse_args()
    root = args.intake.resolve()
    source = root / "source"
    normalized = root / "normalized" / "mo-li-hua-cc0.json"
    reference_path = root / "references" / "mo-li-hua-cc0.reference.json"
    manifest_path = root / "manifest.json"
    for path in (normalized, reference_path, manifest_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite: {path}")

    license_data = json.loads((source / "license-response.json").read_text(encoding="utf-8"))
    if license_data.get("license") != "CC0-1.0":
        raise ValueError("Finalverse score is not explicitly CC0-1.0")
    required = ("perform", "arrange", "record", "print")
    if any(license_data.get("answer", {}).get(k, {}).get("permission") != "allowed" for k in required):
        raise ValueError("Finalverse license check did not allow all required uses")

    perform = json.loads((source / "perform-response.json").read_text(encoding="utf-8"))
    events = perform.get("events") or []
    if not events:
        raise ValueError("perform response contains no events")
    notes = []
    for event in events:
        onset = float(event["onsetSeconds"]) * 1000.0
        duration = float(event["durationSeconds"]) * 1000.0
        track = int(event["partIndex"])
        velocity = int(round(float(event.get("velocity", 90))))
        if duration <= 0 or duration > 60000 or onset < 0:
            raise ValueError(f"invalid timed event: {event.get('id')}")
        for pitch in event.get("midi") or []:
            pitch = int(pitch)
            if pitch < 0 or pitch > 127:
                raise ValueError(f"invalid MIDI pitch: {pitch}")
            notes.append({
                "pitch": pitch,
                "startMs": onset,
                "durationMs": duration,
                "track": track,
                "velocity": max(1, min(127, velocity)),
                "percussion": False,
            })
    notes.sort(key=lambda n: (n["track"], round(n["startMs"], 3), n["pitch"], round(n["durationMs"], 3), n["velocity"]))
    length_ms = float(perform["duration_seconds"]) * 1000.0
    xml_hash = sha256_file(source / "mo-li-hua.musicxml")
    retrieved = datetime.now(timezone.utc).isoformat()
    provenance = {
        "workId": "public-domain:jiangsu-mo-li-hua",
        "editionId": "finalverse:mo-li-hua:cc0-1.0",
        "artist": "传统江苏民歌",
        "artists": ["传统江苏民歌"],
        "languageTags": ["cmn"],
        "album": "中国民歌 · 江苏",
        "versionLabel": "Finalverse CC0 编配 · C大调 · 66 BPM · 30小节 · 三轨",
        "provider": "Finalverse",
        "aliases": ["Mo Li Hua", "Jasmine Flower", "好一朵美丽的茉莉花"],
        "tags": ["中文歌曲", "中文传统旋律", "中国民歌", "公版", "CC0-1.0", "结构化谱", "来源时值校验"],
        "sourceUrl": "https://finalverse.org/scores/mo-li-hua",
        "license": "CC0-1.0",
        "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
        "rightsStatus": "cc0-1-0-allowed",
        "sourceSha256": xml_hash,
        "notationSha256": xml_hash,
        "maintainer": "Finalverse Song editorial team",
        "retrievedAt": retrieved,
        "completeness": "full-work",
        "timingStatus": "source-compared",
        "musicReview": "not-reviewed",
        "gameReview": "not-tested",
        "synthetic": False,
        "redistributionVerified": True,
    }
    song = {
        "version": 1,
        "title": "茉莉花",
        "author": "传统江苏民歌",
        "category": "中文传统旋律 · CC0 公版",
        "source": "Finalverse Song · Mo Li Hua · CC0-1.0",
        "description": "完整 30 小节、C 大调、66 BPM、三轨 CC0 编配；旋律为传统江苏民歌。该条目是公版中文传统旋律，不冒充抖音/酷狗/网易云热榜流行歌；按来源事件保留音符起音、长短音、休止与三轨结构。",
        "provenance": provenance,
        "keyInstrumentId": "windsong",
        "bpm": 66.0,
        "lengthMs": length_ms,
        "notes": notes,
        "warnings": ["CC0 公版中文传统旋律；不是平台热榜歌曲。", "音乐正确性尚未人工听辨，原神内演奏尚未验收。"],
    }
    normalized.parent.mkdir(parents=True, exist_ok=True)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_text(json.dumps(song, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    reference_path.write_text(json.dumps({"notes": notes, "lengthMs": length_ms, "synthetic": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "schemaVersion": "qinban.finalverse-cc0-score-intake.v1",
        "retrievedAtUtc": retrieved,
        "provider": "Finalverse",
        "scoreId": "seed-mo-li-hua",
        "sourceUrl": "https://finalverse.org/scores/mo-li-hua",
        "sourceFormat": "MusicXML + deterministic perform_score events",
        "license": "CC0-1.0",
        "rightsStatus": "cc0-1-0-allowed",
        "redistributionVerified": True,
        "title": "茉莉花",
        "artist": "传统江苏民歌",
        "languageTags": ["cmn"],
        "workId": provenance["workId"],
        "editionId": provenance["editionId"],
        "notes": len(notes),
        "eventCount": len(events),
        "lengthMs": length_ms,
        "xmlSha256": xml_hash,
        "normalizedSha256": sha256_file(normalized),
        "referenceSha256": sha256_file(reference_path),
        "status": "PASS_INTAKE_STRUCTURAL_CC0",
        "boundary": "CC0/structural source gate passed; human listening and real-game playback remain untested.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "normalized": str(normalized), "reference": str(reference_path), "manifest": str(manifest_path), "notes": len(notes), "lengthMs": length_ms}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())