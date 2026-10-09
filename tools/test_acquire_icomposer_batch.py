"""iComposer \u5019\u9009\u91c7\u96c6\u5668\u7684\u9694\u79bb\u3001\u786e\u5b9a\u6027\u548c\u62d2\u7edd\u8def\u5f84\u6d4b\u8bd5\u3002"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("acquire_icomposer_batch.py")
spec = importlib.util.spec_from_file_location("acquire_icomposer_batch", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IComposerBatchTests(unittest.TestCase):
    def make_fixture(self, *, note: str | None = None, duration: str | None = None, name: str = "test-song.txt") -> Path:
        root = Path(tempfile.mkdtemp(prefix="icomposer-fixture-"))
        (root / "dataset" / "lyrics_note").mkdir(parents=True)
        (root / "dataset" / "lyrics_duration").mkdir(parents=True)
        (root / "README.md").write_text("fixture README without license", encoding="utf-8")
        (root / "dataset" / "lyrics_note" / name).write_text(
            note if note is not None else "test song\n60 62\nhello world\n64 65\n",
            encoding="utf-8",
        )
        (root / "dataset" / "lyrics_duration" / name).write_text(
            duration if duration is not None else "test song\n0.5 0.5\nhello world\n0.25 0.75\n",
            encoding="utf-8",
        )
        return root

    def test_same_input_is_deterministic(self) -> None:
        fixture = self.make_fixture()
        kwargs = dict(
            no_network=True,
            fixture_dir=fixture,
            count=1,
            seed=123,
            provider="iComposer",
            retrieval_time="2026-10-07T00:00:00+00:00",
        )
        first = mod.run_acquisition(**kwargs)
        second = mod.run_acquisition(**kwargs)
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["references"], second["references"])
        self.assertEqual(first["sourceAudit"], second["sourceAudit"])
        self.assertEqual(first["reportSha256"], second["reportSha256"])
        self.assertEqual(first["accepted"][0]["notes"][2]["start"], 1)

    def test_bad_format_is_rejected(self) -> None:
        fixture = self.make_fixture(note="test song\n60 X\n", duration="test song\n0.5 0.5\n")
        with self.assertRaisesRegex(mod.IntakeError, "empty batch rejected"):
            mod.run_acquisition(no_network=True, fixture_dir=fixture, count=1)

    def test_bad_format_direct_parser_reports_rejection(self) -> None:
        with self.assertRaisesRegex(mod.IntakeError, "note format rejected"):
            mod.parse_song_payload(
                "bad-format",
                "bad lyric\n60 X\n".encode(),
                "bad lyric\n0.5 0.5\n".encode(),
                source_sha256="A" * 64,
                note_sha256="A" * 64,
                note_url="fixture://note",
                duration_url="fixture://duration",
                source_commit="fixture-commit",
                source_tree="fixture-tree",
                retrieved_at="2026-10-07T00:00:00+00:00",
            )

    def test_note_duration_length_mismatch_rejected(self) -> None:
        fixture = self.make_fixture(note="test song\n60 62\n", duration="test song\n0.5\n")
        with self.assertRaisesRegex(mod.IntakeError, "empty batch rejected"):
            mod.run_acquisition(no_network=True, fixture_dir=fixture, count=1)

    def test_empty_batch_rejected(self) -> None:
        fixture = self.make_fixture(note="", duration="")
        with self.assertRaisesRegex(mod.IntakeError, "empty batch rejected"):
            mod.run_acquisition(no_network=True, fixture_dir=fixture, count=1)

    def test_missing_license_uses_conservative_rights(self) -> None:
        fixture = self.make_fixture()
        result = mod.run_acquisition(no_network=True, fixture_dir=fixture, count=1)
        entry = result["manifest"]["entries"][0]
        self.assertEqual(entry["License"], "dataset-license-not-stated")
        self.assertEqual(entry["RightsStatus"], "candidate-unverified")
        self.assertFalse(entry["redistributionVerified"])
        self.assertEqual(result["sourceAudit"]["source"]["licenseFiles"], [])
        self.assertTrue(result["sourceAudit"]["source"]["readmePresent"])

    def test_report_and_hash_are_reproducible_and_write_is_explicit(self) -> None:
        fixture = self.make_fixture()
        with tempfile.TemporaryDirectory(prefix="icomposer-output-") as output:
            result = mod.run_acquisition(
                no_network=True,
                fixture_dir=fixture,
                count=1,
                output_dir=Path(output),
                write=True,
                retrieval_time="2026-10-07T00:00:00+00:00",
            )
            self.assertEqual(
                sorted(path.name for path in Path(output).iterdir()),
                ["README.md", "manifest.json", "references.json", "source-audit.json"],
            )
            manifest = json.loads((Path(output) / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["entries"][0]["ResearchCandidate"])
            self.assertFalse(manifest["entries"][0]["ProductionBuiltin"])
            second = mod.run_acquisition(
                no_network=True,
                fixture_dir=fixture,
                count=1,
                retrieval_time="2026-10-07T00:00:00+00:00",
            )
            self.assertEqual(result["reportSha256"], second["reportSha256"])


if __name__ == "__main__":
    unittest.main()
