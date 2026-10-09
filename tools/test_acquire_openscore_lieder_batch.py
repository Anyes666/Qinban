"""Offline tests for the OpenScore Lieder intake.

All conversion and process behavior is injected.  These tests do not invoke
MuseScore, the network, QinBan, a game, native input, elevation, or --apply.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import acquire_openscore_lieder_batch as intake  # noqa: E402


def vlq(value: int) -> bytes:
    result = [value & 0x7F]
    value >>= 7
    while value:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(result))


def midi_bytes(*, pitch: int = 60, bpm: float = 120.0, duration_ms: float = 1000.0, invalid_same_tick: bool = False) -> bytes:
    tempo = int(round(60_000_000 / bpm))
    ticks = max(1, int(round(duration_ms * 480_000 / tempo)))
    track = b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    track += b"\x00\x90" + bytes((pitch, 100))
    track += (b"\x00" if invalid_same_tick else vlq(ticks)) + b"\x80" + bytes((pitch, 64))
    track += b"\x00\xff\x2f\x00"
    return b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (480).to_bytes(2, "big") + b"MTrk" + len(track).to_bytes(4, "big") + track


def musicxml_bytes(title: str, composer: str, *, source: str = "https://musescore.com/user/1/scores/100", language: str = "", lyric: str = "hello") -> bytes:
    language_xml = f"<miscellaneous><miscellaneous-field name=\"language\">{language}</miscellaneous-field></miscellaneous>" if language else ""
    xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<score-partwise version=\"4.0\">
  <work><work-title>{title}</work-title></work>
  <identification>
    <creator type=\"composer\">{composer}</creator>
    <source>{source}</source>
    <rights>OpenScore (CC0)</rights>
    {language_xml}
  </identification>
  <part id=\"P1\"><measure number=\"1\"><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><lyric><text>{lyric}</text></lyric></note></measure></part>
</score-partwise>"""
    return xml.encode("utf-8")


def mxl_bytes(xml: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", "<container><rootfiles><rootfile full-path=\"score.xml\"/></rootfiles></container>")
        archive.writestr("score.xml", xml)
    return output.getvalue()


def make_source(root: Path, *, count: int = 2, same_work: bool = True) -> Path:
    source = root / "openscore-source"
    (source / "data").mkdir(parents=True)
    (source / "LICENSE.txt").write_text("CC0 1.0 Universal\n", encoding="utf-8")
    rows = []
    for index in range(count):
        score_id = 100 + index
        folder = f"Composer/_/Edition_{index + 1}"
        title = "Same Song" if same_work else f"Song {index + 1}"
        directory = source / "scores" / folder
        directory.mkdir(parents=True)
        xml = musicxml_bytes(title, "Example Composer", source=f"https://musescore.com/user/1/scores/{score_id}", language="EN" if index == 0 else "", lyric="hello")
        (directory / f"lc{score_id}.mxl").write_bytes(mxl_bytes(xml))
        (directory / f"lc{score_id}.mscz").write_bytes(f"mscz-fixture-{score_id}".encode())
        rows.append(f"{score_id}:\n  path: {folder}\n  set_id: {900 + index}\n  language: {'EN' if index == 0 else 'Unknown'}\n")
    (source / "data" / "scores.yaml").write_text("".join(rows), encoding="utf-8")
    return source


def converter_for(pitches: list[int], *, same: bool = False, fail: bool = False):
    def converter(executable, jobs, job_path):
        if fail:
            raise RuntimeError("injected converter failure")
        for index, job in enumerate(jobs):
            pitch = pitches[0] if same else pitches[index % len(pitches)]
            Path(job["out"]).write_bytes(midi_bytes(pitch=pitch))
    return converter


class OpenScoreIntakeTests(unittest.TestCase):
    def call(self, source: Path, output: Path, **kwargs):
        kwargs.setdefault("source_commit", "a" * 40)
        kwargs.setdefault("catalog_root", output.parent.parent if output.parent.name else output.parent)
        kwargs.setdefault("now_fn", lambda: "2026-10-06T00:00:00+00:00")
        return intake.acquire_batch(source, output, **kwargs)

    def test_csv_and_musicxml_metadata(self) -> None:
        rows = intake._parse_tabular_metadata("id,path,language\n123,Composer/_/Song,EN\n")
        self.assertEqual(rows["123"]["path"], "Composer/_/Song")
        parsed = intake._parse_musicxml(musicxml_bytes("Exact Title", "Exact Composer", language="DE"))
        self.assertEqual(parsed["title"], "Exact Title")
        self.assertEqual(parsed["composer"], "Exact Composer")
        self.assertEqual(parsed["source"], "https://musescore.com/user/1/scores/100")
        self.assertEqual(parsed["xmlLanguages"], ["DE"])

    def test_work_edition_hash_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-work-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=2, same_work=True)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            result = self.call(source, output, limit=2, converter=converter_for([60, 62]), open_fn=open)
            songs = result["manifest"]["Songs"]
            self.assertEqual(len(songs), 2)
            self.assertEqual({song["WorkId"] for song in songs}, {"openscore-work:same-song::example-composer"})
            self.assertEqual(len({song["EditionId"] for song in songs}), 2)
            self.assertEqual(len({song["SourceSha256"] for song in songs}), 2)
            self.assertTrue(all("OpenScore score" in song["Title"] for song in songs))
            self.assertTrue(all(song["RightsStatus"] == "candidate-unverified" for song in songs))
            self.assertTrue(all(song["RedistributionVerified"] is False for song in songs))
            self.assertEqual(result["manifest"]["SourceCommit"], "a" * 40)
            records = list((output / "metadata" / "records").glob("*.json"))
            self.assertEqual(len(records), 2)
            record = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(record["source"]["commit"], "a" * 40)
            self.assertTrue(record["source"]["rawFiles"]["mxl"]["sha256"])
            self.assertTrue(record["source"]["rawFiles"]["mscz"]["sha256"])
            self.assertEqual(record["language"]["tags"], ["en"])
            self.assertEqual(result["report"]["selectedCount"], 2)

    def test_exclude_manifest_skips_edition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-exclude-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=2)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            first = catalog / "first"
            self.call(source, first, limit=1, converter=converter_for([60]))
            second = catalog / "second"
            result = self.call(source, second, limit=1, converter=converter_for([62]), exclude_manifests=[first / "manifest.json"])
            self.assertEqual(result["manifest"]["Songs"][0]["Id"], "openscore-lieder-101")
            self.assertEqual(len(result["report"]["skippedByExclude"]), 1)

    def test_duplicate_midi_fails_and_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-duplicate-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=2)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            with self.assertRaises(intake.IntakeError) as context:
                self.call(source, output, limit=2, converter=converter_for([60], same=True))
            self.assertFalse(output.exists())
            self.assertTrue(any(item["stage"] == "duplicate" for item in context.exception.failures))

    def test_failure_is_recorded_for_each_selected_score_and_no_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-failure-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=2)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            with self.assertRaises(intake.IntakeError) as context:
                self.call(source, output, limit=2, converter=converter_for([60, 62], fail=True))
            self.assertFalse(output.exists())
            ids = {item.get("id") for item in context.exception.failures}
            self.assertEqual(ids, {"openscore-lieder-100", "openscore-lieder-101"})

    def test_allow_partial_publishes_only_individually_valid_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-partial-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=2)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"

            class Result:
                returncode = 1303
                stdout = "partial conversion"
                stderr = "one score rejected"

            def runner(command, **kwargs):
                jobs = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                Path(jobs[0]["out"]).write_bytes(midi_bytes(pitch=60))
                Path(jobs[1]["out"]).write_bytes(midi_bytes(pitch=62, invalid_same_tick=True))
                return Result()

            result = self.call(
                source,
                output,
                limit=2,
                musescore_exe="MuseScore4.exe",
                process_runner=runner,
                allow_partial=True,
            )
            self.assertTrue(output.exists())
            self.assertEqual(len(result["manifest"]["Songs"]), 1)
            self.assertEqual(result["report"]["status"], "PASS_OPENSCORE_LIEDER_PARTIAL_CANDIDATE_INTAKE")
            self.assertEqual(result["report"]["requestedCount"], 2)
            self.assertEqual(result["report"]["acceptedCount"], 1)
            self.assertEqual(result["report"]["conversionRejectedCount"], 1)
            self.assertEqual(len(list((output / "midi").glob("*.mid"))), 1)

    def test_existing_output_is_refused_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-existing-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=1)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(intake.IntakeError):
                self.call(source, output, limit=1, converter=converter_for([60]))
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_missing_cli_fails_closed_before_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-cli-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=1)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            with self.assertRaises(intake.IntakeError) as context:
                self.call(source, output, limit=1)
            self.assertFalse(output.exists())
            self.assertEqual(context.exception.failures[0]["stage"], "preflight")
    def test_musescore_job_runner_command_and_injected_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openscore-job-") as temporary:
            root = Path(temporary)
            source = make_source(root, count=1)
            catalog = root / "catalog-intake"
            catalog.mkdir()
            output = catalog / "batch"
            calls = []

            def tracked_open(path, mode):
                calls.append((Path(path).name, mode))
                return open(path, mode)

            class Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def runner(command, **kwargs):
                self.assertEqual(command[1:4], ["--test-mode", "-F", "-j"])
                jobs = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                self.assertEqual(len(jobs), 1)
                Path(jobs[0]["out"]).write_bytes(midi_bytes(pitch=65))
                return Result()

            result = self.call(source, output, limit=1, musescore_exe="MuseScore4.exe", process_runner=runner, open_fn=tracked_open)
            self.assertEqual(result["report"]["converter"]["returncode"], 0)
            self.assertTrue(any(name == "scores.yaml" for name, _ in calls))
            self.assertTrue(any("--test-mode" in value for value in result["report"]["converter"]["command"]))

    def test_bpm_boundaries_and_strict_parser(self) -> None:
        self.assertTrue(intake._validate_midi(midi_bytes(bpm=20.0), "bpm20")["notes"])
        self.assertTrue(intake._validate_midi(midi_bytes(bpm=400.0), "bpm400")["notes"])
        with self.assertRaises(intake.IntakeError):
            intake._validate_midi(midi_bytes(bpm=19.0), "bpm19")
        with self.assertRaises(intake.IntakeError):
            intake._validate_midi(midi_bytes(bpm=401.0), "bpm401")
        with self.assertRaises(intake.IntakeError):
            intake._validate_midi(midi_bytes(invalid_same_tick=True), "nonpositive")


if __name__ == "__main__":
    unittest.main(verbosity=2)