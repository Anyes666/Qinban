"""Read-only POP100 source-note gap audit; stdlib + independent parse_smf only.

Run with python -B tools/diagnose_pop100_gaps.py [--self-test | --check-only].
The only report destination is fixed below and is created exclusively, never replaced.
No audio, input injection, production imports, network, or mido are used.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import sys
import unittest

sys.dont_write_bytecode = True
from smf_reference import parse_smf

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "catalog-intake/pop100-2026-10-06"
OUTPUT = ROOT / ".validation/pop100-gap-diagnosis-2026-10-06/source-gap-audit.json"
THRESHOLD_MS = 5000.0
TIMING_TOLERANCE_MS = 0.002
EPS_MS = 1e-7
MODES = {"melody": [1], "melody_bridge": [1, 2], "all_tracks": None}


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def seconds(ms):
    return round(ms / 1000.0, 9)


def interval_record(start, end):
    return {"startSeconds": seconds(start), "endSeconds": seconds(end),
            "durationSeconds": seconds(end - start)}


def merge_intervals(intervals):
    """Union note-active half-open intervals; overlaps/adjacency are not silence."""
    merged = []
    for start, end in sorted(intervals):
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("invalid note interval")
        if merged and start <= merged[-1][1] + EPS_MS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def silence_intervals(active, length):
    cursor = 0.0
    gaps = []
    for start, end in active:
        if end > length + TIMING_TOLERANCE_MS:
            raise ValueError("note ends beyond source timeline")
        if start > cursor + EPS_MS:
            gaps.append((cursor, start, "leading" if cursor == 0 else "internal"))
        cursor = max(cursor, end)
    if length > cursor + EPS_MS:
        gaps.append((cursor, length, "trailing" if active else "whole_timeline"))
    return gaps


def coverage(start, end, intervals):
    clipped = merge_intervals((max(start, a), min(end, b))
                             for a, b in intervals if min(end, b) > max(start, a))
    remaining = []
    cursor = start
    for a, b in clipped:
        if a > cursor + EPS_MS:
            remaining.append((cursor, a))
        cursor = b
    if end > cursor + EPS_MS:
        remaining.append((cursor, end))
    covered = sum(b - a for a, b in clipped)
    duration = end - start
    return {"coveredSeconds": seconds(covered),
            "coverageRatio": round(covered / duration, 9),
            "fullyCovered": duration - covered <= EPS_MS,
            "activeIntervals": [interval_record(a, b) for a, b in clipped],
            "uncoveredSeconds": seconds(duration - covered),
            "uncoveredIntervals": [interval_record(a, b) for a, b in remaining],
            "uncoveredAtLeast5Seconds": [interval_record(a, b) for a, b in remaining
                                          if b - a + EPS_MS >= THRESHOLD_MS]}


def analyze(notes, length, selected, detailed=True):
    tracks = sorted({n["track"] for n in notes}) if selected is None else list(selected)
    chosen = [n for n in notes if n["track"] in tracks]
    active = merge_intervals((n["startMs"], n["startMs"] + n["durationMs"]) for n in chosen)
    gaps = silence_intervals(active, length)
    long_gaps = []
    for start, end, kind in gaps:
        if end - start + EPS_MS < THRESHOLD_MS:
            continue
        gap = {"kind": kind, **interval_record(start, end)}
        if detailed:
            other = sorted(set(n["track"] for n in notes) - set(tracks))
            gap["otherTrackCoverage"] = {}
            for track in other:
                intervals = [(n["startMs"], n["startMs"] + n["durationMs"])
                             for n in notes if n["track"] == track]
                gap["otherTrackCoverage"][str(track)] = coverage(start, end, intervals)
            intervals = [(n["startMs"], n["startMs"] + n["durationMs"])
                         for n in notes if n["track"] in other]
            gap["otherTracksUnionCoverage"] = coverage(start, end, intervals)
        long_gaps.append(gap)
    internal = [g for g in long_gaps if g["kind"] == "internal"]
    all_internal = [(a, b) for a, b, kind in gaps if kind == "internal"]
    return {"tracks": tracks, "noteCount": len(chosen), "activeIntervalCount": len(active),
            "timelineSeconds": seconds(length),
            "firstNoteOnSeconds": seconds(active[0][0]) if active else None,
            "lastNoteOffSeconds": seconds(active[-1][1]) if active else None,
            "leadingSilenceSeconds": seconds(active[0][0]) if active else seconds(length),
            "trailingSilenceSeconds": seconds(max(0, length - active[-1][1])) if active else None,
            "activeSeconds": seconds(sum(b - a for a, b in active)),
            "maxInternalSilenceSeconds": seconds(max((b - a for a, b in all_internal), default=0)),
            "internalLongGapCount": len(internal),
            "internalLongSilenceSeconds": round(sum(g["durationSeconds"] for g in internal), 9),
            "longGapCountIncludingEdges": len(long_gaps),
            "longSilenceSecondsIncludingEdges": round(sum(g["durationSeconds"] for g in long_gaps), 9),
            "longGaps": long_gaps}


def track_names(data):
    """Read track-name metadata only; note timing exclusively comes from parse_smf."""
    pos = 8 + int.from_bytes(data[4:8], "big")
    count = struct.unpack(">H", data[10:12])[0]
    result = {}

    def vlq(buf, at):
        value = 0
        for _ in range(4):
            byte = buf[at]
            at += 1
            value = (value << 7) | (byte & 127)
            if byte < 128:
                return value, at
        raise ValueError("invalid metadata VLQ")

    for track in range(count):
        if data[pos:pos + 4] != b"MTrk":
            raise ValueError("missing metadata track")
        size = int.from_bytes(data[pos + 4:pos + 8], "big")
        buf = data[pos + 8:pos + 8 + size]
        pos += 8 + size
        at, running = 0, None
        names = []
        while at < len(buf):
            _, at = vlq(buf, at)
            status = buf[at]
            if status >= 128:
                at += 1
            elif running is not None:
                status = running
            else:
                raise ValueError("metadata running status missing")
            if status == 0xff:
                kind = buf[at]
                at += 1
                length, at = vlq(buf, at)
                payload = buf[at:at + length]
                at += length
                if kind == 3:
                    names.append(payload.decode("utf-8", errors="replace"))
                if kind == 0x2f:
                    break
            elif status in (0xf0, 0xf7):
                length, at = vlq(buf, at)
                at += length
                running = None
            elif 0x80 <= status < 0xf0:
                running = status
                at += 1 if status & 0xf0 in (0xc0, 0xd0) else 2
            else:
                raise ValueError("unsupported metadata event")
        result[str(track)] = names
    return result


def compare_score(score, reference):
    def ordered(notes):
        return sorted(notes, key=lambda n: (n["track"], n["startMs"], n["pitch"],
                                           n["durationMs"], n["velocity"]))
    left, right = ordered(score["notes"]), ordered(reference["notes"])
    errors = []
    if len(left) != len(right):
        errors.append(f"note count differs: JSON={len(left)}, MIDI={len(right)}")
    categorical_mismatches = 0
    max_start = max_duration = max_end = 0.0
    for x, y in zip(left, right):
        if any(x[k] != y[k] for k in ("pitch", "track", "velocity", "percussion")):
            categorical_mismatches += 1
        max_start = max(max_start, abs(x["startMs"] - y["startMs"]))
        max_duration = max(max_duration, abs(x["durationMs"] - y["durationMs"]))
        max_end = max(max_end, abs(x["startMs"] + x["durationMs"] - y["startMs"] - y["durationMs"]))
    length_error = abs(score["lengthMs"] - reference["lengthMs"])
    if categorical_mismatches:
        errors.append(f"note attributes differ: {categorical_mismatches}")
    if max(max_start, max_duration, length_error) > TIMING_TOLERANCE_MS:
        errors.append("note timing/timeline exceeds 0.002 ms tolerance")
    return {"passed": not errors, "errors": errors, "sourceNoteCount": len(right),
            "jsonNoteCount": len(left), "categoricalMismatchCount": categorical_mismatches,
            "maxStartErrorMs": max_start, "maxDurationErrorMs": max_duration,
            "maxNoteOffErrorMs": max_end, "timelineErrorMs": length_error}


def compare_gaps(source, normalized):
    errors = []
    max_error = 0.0
    for mode in MODES:
        a, b = source[mode], normalized[mode]
        if len(a["longGaps"]) != len(b["longGaps"]):
            errors.append(f"{mode}: long-gap count differs")
        for x, y in zip(a["longGaps"], b["longGaps"]):
            if x["kind"] != y["kind"]:
                errors.append(f"{mode}: gap kind differs")
            for key in ("startSeconds", "endSeconds"):
                max_error = max(max_error, abs(x[key] - y[key]) * 1000)
        for key in ("firstNoteOnSeconds", "lastNoteOffSeconds"):
            if (a[key] is None) != (b[key] is None):
                errors.append(f"{mode}: empty selection differs")
            elif a[key] is not None:
                max_error = max(max_error, abs(a[key] - b[key]) * 1000)
    if max_error > TIMING_TOLERANCE_MS * 2:
        errors.append("gap boundaries exceed note endpoint tolerance")
    return {"passed": not errors, "maxBoundaryErrorMs": max_error, "errors": errors}


def summarize(rows, failures):
    summary = {"requestedSongs": 100, "scannedSongs": len(rows) + len(failures),
               "auditedSongs": len(rows), "failedSongs": len(failures),
               "sourceTimingPassedSongs": sum(r["comparison"]["passed"] for r in rows),
               "gapComparisonPassedSongs": sum(r["gapComparison"]["passed"] for r in rows),
               "defaultMelodyOnlySongs": sum(r["catalogDefaultTracks"] == [1] for r in rows),
               "sourceNotesCompared": sum(r["comparison"]["sourceNoteCount"] for r in rows),
               "maxTimingErrorMs": max((max(r["comparison"][k] for k in
                   ("maxStartErrorMs", "maxDurationErrorMs", "timelineErrorMs")) for r in rows), default=0),
               "modes": {}}
    for mode in MODES:
        values = [r["sourceModes"][mode] for r in rows]
        summary["modes"][mode] = {
            "songsWithInternalLongGaps": sum(v["internalLongGapCount"] > 0 for v in values),
            "internalLongGapCount": sum(v["internalLongGapCount"] for v in values),
            "internalLongSilenceSeconds": round(sum(v["internalLongSilenceSeconds"] for v in values), 9),
            "songsWithLeadingSilenceAtLeast5s": sum(v["leadingSilenceSeconds"] + 1e-10 >= 5 for v in values),
            "songsWithTrailingSilenceAtLeast5s": sum((v["trailingSilenceSeconds"] or 0) + 1e-10 >= 5 for v in values),
            "longGapCountIncludingEdges": sum(v["longGapCountIncludingEdges"] for v in values),
            "maxInternalSilenceSeconds": max((v["maxInternalSilenceSeconds"] for v in values), default=0)}
    summary["melodyCoverage"] = {}
    for label, kinds in (("internal", {"internal"}), ("includingEdges", {"internal", "leading", "trailing", "whole_timeline"})):
        gaps = [g for r in rows for g in r["sourceModes"]["melody"]["longGaps"] if g["kind"] in kinds]
        duration = sum(g["durationSeconds"] for g in gaps)
        union_covered = sum(g["otherTracksUnionCoverage"]["coveredSeconds"] for g in gaps)
        summary["melodyCoverage"][label] = {
            "gapCount": len(gaps), "gapSeconds": round(duration, 9),
            "bridgeCoveredSeconds": round(sum(g["otherTrackCoverage"].get("2", {}).get("coveredSeconds", 0) for g in gaps), 9),
            "pianoCoveredSeconds": round(sum(g["otherTrackCoverage"].get("3", {}).get("coveredSeconds", 0) for g in gaps), 9),
            "otherTracksUnionCoveredSeconds": round(union_covered, 9),
            "weightedUnionCoverageRatio": round(union_covered / duration, 9) if duration else None,
            "fullyCoveredGapCount": sum(g["otherTracksUnionCoverage"]["fullyCovered"] for g in gaps),
            "partiallyCoveredGapCount": sum(0 < g["otherTracksUnionCoverage"]["coveredSeconds"] < g["durationSeconds"] for g in gaps),
            "uncoveredGapCount": sum(g["otherTracksUnionCoverage"]["coveredSeconds"] == 0 for g in gaps),
            "remainingAtLeast5sIntervalCount": sum(len(g["otherTracksUnionCoverage"]["uncoveredAtLeast5Seconds"]) for g in gaps)}
    return summary


def audit():
    manifest_bytes = (INTAKE / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    songs = manifest["songs"]
    ids = [s["id"] for s in songs]
    if len(ids) != 100 or len(set(ids)) != 100:
        raise ValueError("manifest must contain exactly 100 distinct songs")
    expected = {f"pop909-{sid}.json" for sid in ids}
    if {p.name for p in (ROOT / "Songs").glob("pop909-*.json")} != expected:
        raise ValueError("Songs/pop909-*.json set does not match all 100 manifest IDs")
    catalog_path = ROOT / "Songs/catalog.db"
    if any(Path(str(catalog_path) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise ValueError("catalog has transaction sidecars; immutable read would be unsafe/stale")
    catalog_bytes = catalog_path.read_bytes()
    con = sqlite3.connect(catalog_path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        defaults = {sid: json.loads(metadata)["options"]["tracks"] for sid, metadata in
                    con.execute("SELECT id,metadata_json FROM entries WHERE id LIKE 'builtin:pop909-%'")}
    finally:
        con.close()
    rows, failures, input_hashes = [], [], {}
    for song in sorted(songs, key=lambda s: s["id"]):
        sid = song["id"]
        try:
            midi_path = Path(song["midiPath"])
            if midi_path.resolve() != (INTAKE / f"midi/{sid}.mid").resolve():
                raise ValueError("source path is outside the expected local intake")
            json_path = ROOT / f"Songs/pop909-{sid}.json"
            midi_bytes, json_bytes = midi_path.read_bytes(), json_path.read_bytes()
            input_hashes[midi_path] = sha(midi_bytes)
            input_hashes[json_path] = sha(json_bytes)
            score = json.loads(json_bytes.decode("utf-8"))
            reference = parse_smf(midi_bytes)
            names = track_names(midi_bytes)
            if any(names.get(str(t)) != [name] for t, name in ((1, "MELODY"), (2, "BRIDGE"), (3, "PIANO"))):
                raise ValueError(f"unexpected track identity: {names}")
            if sha(midi_bytes) != song["sourceSha256"] or score["provenance"]["sourceSha256"] != sha(midi_bytes):
                raise ValueError("source SHA256 differs from manifest/score provenance")
            if score["title"] != song["title"]:
                raise ValueError("source manifest and score title differ")
            source_modes = {mode: analyze(reference["notes"], reference["lengthMs"], tracks)
                            for mode, tracks in MODES.items()}
            json_modes = {mode: analyze(score["notes"], score["lengthMs"], tracks, detailed=False)
                          for mode, tracks in MODES.items()}
            rows.append({"id": sid, "title": score["title"], "artist": song["artist"],
                         "sourceMidiPath": str(midi_path), "scoreJsonPath": str(json_path),
                         "sourceSha256": sha(midi_bytes), "scoreSha256": sha(json_bytes),
                         "trackNames": names, "catalogDefaultTracks": defaults[f"builtin:pop909-{sid}.json"],
                         "percussionNoteCount": sum(n["percussion"] for n in reference["notes"]),
                         "comparison": compare_score(score, reference),
                         "gapComparison": compare_gaps(source_modes, json_modes),
                         "sourceModes": source_modes, "normalizedModes": json_modes})
        except Exception as exc:
            failures.append({"id": sid, "title": song.get("title"), "errorType": type(exc).__name__, "error": str(exc)})
    input_hashes[INTAKE / "manifest.json"] = sha(manifest_bytes)
    input_hashes[catalog_path] = sha(catalog_bytes)
    unchanged = all(sha(path.read_bytes()) == digest for path, digest in input_hashes.items())
    summary = summarize(rows, failures)
    passed = (len(rows) == 100 and not failures and unchanged
              and summary["sourceTimingPassedSongs"] == 100
              and summary["gapComparisonPassedSongs"] == 100
              and summary["defaultMelodyOnlySongs"] == 100)
    return {"schemaVersion": 1, "auditDateLocal": "2026-10-06", "status": "PASS" if passed else "FAIL",
            "workspace": str(ROOT), "sourceCommit": manifest["sourceCommit"],
            "method": {"parser": "tools/smf_reference.py::parse_smf (independent; no mido)",
                       "parserSha256": sha((ROOT / "tools/smf_reference.py").read_bytes()),
                       "thresholdSeconds": 5, "timingToleranceMs": TIMING_TOLERANCE_MS,
                       "timeOrigin": "MIDI tick zero; global source tempo map; speed 1; no countdown or trim",
                       "activeDefinition": "union of [note start, note end); note-off, not next note-on; no sustain-pedal/reverb extension",
                       "gapDefinition": "internal gaps between merged active intervals >=5s; leading/trailing reported separately against source end-of-track",
                       "coverageDefinition": "other-track interval union clipped to each long gap; BRIDGE/PIANO coverage must not be added (overlap)",
                       "precision": "source seconds rounded to 9 decimals; JSON compared within 0.002ms",
                       "catalogReadMode": "SQLite mode=ro&immutable=1, no WAL/journal present"},
            "safety": {"inputsRehashedUnchanged": unchanged, "inputFilesRehashed": len(input_hashes),
                       "catalogSha256": sha(catalog_bytes), "manifestSha256": sha(manifest_bytes),
                       "nativeKeySendAttempts": 0, "audioPlayed": False, "networkUsed": False,
                       "productionCodeImported": False, "sourceSongsCatalogUserDataWritten": False},
            "limitations": ["This is source-note timing coverage, not audible PCM silence or music correctness certification.",
                            "No playback, UI, game, key mapping, UserData overrides, or production runtime tested.",
                            "All tracks are analyzed as stored, including percussion (count reported per song)."],
            "summary": summary, "focusSongIds": ["035", "038"], "failures": failures, "songs": rows}


def print_summary(report):
    s = report["summary"]
    print(f"{report['status']}: POP909 {s['scannedSongs']}/100 全扫；独立源时序通过 {s['sourceTimingPassedSongs']}/100；"
          f"长休止对照通过 {s['gapComparisonPassedSongs']}/100；默认仅MELODY {s['defaultMelodyOnlySongs']}/100")
    print(f"音符对比 {s['sourceNotesCompared']}；最大时序误差 {s['maxTimingErrorMs']:.9f} ms")
    print("选择                内部>=5s首数  区间数  总静音秒       >=5s首空白/尾空白首数")
    for mode, label in (("melody", "1 MELODY"), ("melody_bridge", "1+2"), ("all_tracks", "全轨")):
        v = s["modes"][mode]
        print(f"{label:<18} {v['songsWithInternalLongGaps']:>6} {v['internalLongGapCount']:>7} "
              f"{v['internalLongSilenceSeconds']:>12.6f}  {v['songsWithLeadingSilenceAtLeast5s']}/{v['songsWithTrailingSilenceAtLeast5s']}")
    for label, v in s["melodyCoverage"].items():
        print(f"MELODY覆盖 {label}: {v['gapCount']}区间/{v['gapSeconds']:.6f}s；"
              f"BRIDGE {v['bridgeCoveredSeconds']:.6f}s；PIANO {v['pianoCoveredSeconds']:.6f}s；"
              f"并集 {v['otherTracksUnionCoveredSeconds']:.6f}s ({(v['weightedUnionCoverageRatio'] or 0)*100:.3f}%)；"
              f"剩余>=5s {v['remainingAtLeast5sIntervalCount']}段")
    for row in report["songs"]:
        if row["id"] not in report["focusSongIds"]:
            continue
        print(f"\n重点 {row['id']} {row['title']} — 源MIDI准确秒区间")
        for mode, value in row["sourceModes"].items():
            print(f"  {mode}: 首音 {value['firstNoteOnSeconds']:.9f}s，尾音 {value['lastNoteOffSeconds']:.9f}s，"
                  f"内部长休止 {value['internalLongGapCount']}，时间轴结束 {value['timelineSeconds']:.9f}s")
            for gap in value["longGaps"]:
                detail = ""
                if mode == "melody":
                    by_track = gap["otherTrackCoverage"]
                    union = gap["otherTracksUnionCoverage"]
                    detail = (f"；BRIDGE {by_track.get('2', {}).get('coveredSeconds', 0):.9f}s"
                              f"；PIANO {by_track.get('3', {}).get('coveredSeconds', 0):.9f}s"
                              f"；并集 {union['coveredSeconds']:.9f}s ({union['coverageRatio']*100:.3f}%)")
                print(f"    {gap['kind']} [{gap['startSeconds']:.9f}, {gap['endSeconds']:.9f}) "
                      f"{gap['durationSeconds']:.9f}s{detail}")
                if mode == "melody":
                    for remaining in union["uncoveredAtLeast5Seconds"]:
                        print(f"      全轨仍静音>=5s [{remaining['startSeconds']:.9f}, {remaining['endSeconds']:.9f})")
    for failure in report["failures"]:
        print("FAIL", json.dumps(failure, ensure_ascii=False))


class GapTests(unittest.TestCase):
    def test_merge_overlap_touching_and_nested(self):
        self.assertEqual(merge_intervals([(5, 9), (0, 4), (3, 6), (9, 10), (1, 2), (12, 13)]), [(0, 10), (12, 13)])

    def test_sustained_note_is_not_onset_gap(self):
        notes = [{"track": 1, "startMs": 0, "durationMs": 20000},
                 {"track": 1, "startMs": 15000, "durationMs": 1000}]
        result = analyze(notes, 20000, [1])
        self.assertEqual(result["internalLongGapCount"], 0)
        self.assertEqual(result["lastNoteOffSeconds"], 20)

    def test_exact_threshold_and_edges_separate(self):
        notes = [{"track": 1, "startMs": 5000, "durationMs": 1000},
                 {"track": 1, "startMs": 11000, "durationMs": 1000}]
        result = analyze(notes, 17000, [1])
        self.assertEqual([g["kind"] for g in result["longGaps"]], ["leading", "internal", "trailing"])
        self.assertEqual(result["internalLongGapCount"], 1)
        notes[1]["startMs"] = 10999
        self.assertEqual(analyze(notes, 17000, [1])["internalLongGapCount"], 0)

    def test_coverage_union_clips_without_double_counting(self):
        result = coverage(5000, 15000, [(0, 7000), (6000, 8000), (13000, 20000)])
        self.assertEqual(result["coveredSeconds"], 5)
        self.assertEqual(result["coverageRatio"], .5)
        self.assertEqual(result["uncoveredAtLeast5Seconds"], [interval_record(8000, 13000)])
        self.assertTrue(coverage(5000, 15000, [(0, 20000)])["fullyCovered"])

    def test_empty_track_and_zero_coverage(self):
        result = analyze([], 10000, [1])
        self.assertIsNone(result["firstNoteOnSeconds"])
        self.assertEqual(result["longGaps"][0]["kind"], "whole_timeline")
        self.assertEqual(coverage(0, 10000, [])["uncoveredSeconds"], 10)

    def test_attribute_and_timing_mismatch_detection(self):
        note = {"track": 1, "pitch": 60, "velocity": 90, "percussion": False, "startMs": 0, "durationMs": 1000}
        ref = {"notes": [note], "lengthMs": 1000}
        self.assertTrue(compare_score(ref, ref)["passed"])
        self.assertTrue(compare_score({"notes": [{**note, "durationMs": 1000.001}], "lengthMs": 1000}, ref)["passed"])
        self.assertFalse(compare_score({"notes": [{**note, "pitch": 61}], "lengthMs": 1000}, ref)["passed"])
        self.assertFalse(compare_score({"notes": [{**note, "durationMs": 1000.003}], "lengthMs": 1000}, ref)["passed"])
        self.assertFalse(compare_score({"notes": [], "lengthMs": 1000}, ref)["passed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--self-test", action="store_true", help="in-memory algorithm tests only; no files written")
    options.add_argument("--check-only", action="store_true", help="full audit to console without writing report")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GapTests))
        return 0 if result.wasSuccessful() else 1
    if not args.check_only and OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing audit; inspect it or use --check-only: {OUTPUT}")
    report = audit()
    print_summary(report)
    if not args.check_only:
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        print(f"审计文件（仅新增）: {OUTPUT}")
    print("安全边界：不播放、不发按键、不联网，不修改源谱/catalog/UserData/生产代码。")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
