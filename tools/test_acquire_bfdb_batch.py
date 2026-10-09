"""Offline BFDB ABC-to-MIDI intake tests.

Fixtures are self-authored and never represent real songs or rights clearance.
The test uses the locally pinned music21 runtime when it is available.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import acquire_bfdb_batch as intake  # noqa: E402

MUSIC21_PATH = ROOT.parent / ".tools" / "python-packages" / "music21-9.9.2"


@unittest.skipUnless(MUSIC21_PATH.is_dir(), "workspace music21 intake runtime is not installed")
class BfdbIntakeTests(unittest.TestCase):
    def test_converts_abc_and_writes_contract_candidate(self) -> None:
        abc = """X:1
T:Fixture Folk Tune
S:https://example.invalid/source
R:Reel
M:4/4
L:1/4
Q:1/4=120
K:C
C D E F | G A B c |
"""
        with tempfile.TemporaryDirectory(prefix="bfdb-intake-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "dataset.csv").write_text(
                "filename,year,title,source,composer/performer,metre,key,tempo,style,digital_transcriber\n"
                "0001.abc,1800,Fixture Folk Tune,https://example.invalid/source,Traditional,4/4,C,120,Reel,fixture\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(source / "tune_abc_files.zip", "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("tune_abc_files/0001.abc", abc)
            output = root / "intake"
            result = intake.acquire_batch(
                source,
                output,
                limit=1,
                music21_path=MUSIC21_PATH,
                enforce_output_root=False,
            )
            self.assertEqual(result["report"]["selectedCount"], 1)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            song = manifest["Songs"][0]
            self.assertEqual(song["Provider"], "BFDB")
            self.assertEqual(song["License"], "CC BY-NC 4.0")
            self.assertEqual(song["Title"], "Fixture Folk Tune")
            self.assertEqual(song["MusicReview"], "not-reviewed")
            self.assertFalse(song["RedistributionVerified"])
            self.assertTrue(Path(song["MidiPath"]).is_file())
            self.assertTrue(Path(song["ReferencePath"]).is_file())
            reference = json.loads(Path(song["ReferencePath"]).read_text(encoding="utf-8"))
            self.assertGreater(len(reference["notes"]), 0)
            self.assertEqual(result["report"]["uniqueSourceSha256"], 1)

    def test_empty_limit_is_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bfdb-intake-empty-") as temporary:
            root = Path(temporary)
            with self.assertRaises(intake.IntakeError):
                intake.acquire_batch(root, root / "out", limit=0, enforce_output_root=False)

    def test_source_tempo_must_fit_runtime_bpm_budget(self) -> None:
        valid = {"notes": [{"pitch": 60}], "bpm": 120, "lengthMs": 1000}
        intake._validate_source_reference(valid)
        for bpm in (19.99, 400.01, float("nan"), float("inf")):
            with self.subTest(bpm=bpm):
                reference = {**valid, "bpm": bpm}
                with self.assertRaisesRegex(intake.IntakeError, "BPM outside QinBan budget"):
                    intake._validate_source_reference(reference)

    def test_control_characters_in_display_metadata_are_rejected(self) -> None:
        with self.assertRaisesRegex(intake.IntakeError, "title contains a control character"):
            intake._validate_display_text("John Malchair\x92s", "title")
        with self.assertRaisesRegex(intake.IntakeError, "artist contains a control character"):
            intake._validate_display_text("composer\x85", "artist")


if __name__ == "__main__":
    unittest.main(verbosity=2)