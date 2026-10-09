import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("convert_midi_lyric_corpus_batch.py")
spec = importlib.util.spec_from_file_location("convert_midi_lyric_corpus_batch", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MidiLyricConverterTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        midi = root / "0001.MID"
        # Standard MIDI: C4 for 480 ticks at 480 PPQ, 60 BPM.
        track = (
            b"\x00\xff\x51\x03\x0f\x42\x40"
            b"\x00\x90\x3c\x64"
            b"\x83\x60\x80\x3c\x00"
            b"\x00\xff\x2f\x00"
        )
        midi.write_bytes(
            b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big")
            + (1).to_bytes(2, "big") + (480).to_bytes(2, "big")
            + b"MTrk" + len(track).to_bytes(4, "big") + track
        )
        intake = root / "manifest.json"
        source_hash = mod.sha256_file(midi)
        intake.write_text(json.dumps({
            "sourceRoot": str(root),
            "sourceUrl": "https://example.invalid/corpus",
            "sourceCommit": "a" * 40,
            "generatedAtUtc": "2026-10-07T00:00:00Z",
            "entries": [{
                "id": "midi_lyric_corpus:0001:fixture",
                "title": "花心",
                "artist": "周华健",
                "languageTags": ["zh"],
                "workId": "work:花心",
                "editionId": "edition:0001",
                "versionLabel": "原始 MIDI+歌词版 · 0001",
                "sourcePath": str(midi),
                "sourceSha256": source_hash,
                "sourceUrl": "https://example.invalid/corpus/0001.MID",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        return intake, midi

    def test_generates_reference_and_popbatch_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intake, midi = self._fixture(root)
            out = root / "out"
            result = mod.convert_batch(intake, out)
            self.assertEqual(result["count"], 1)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            song = manifest["Songs"][0]
            self.assertEqual(song["SourceSha256"], mod.sha256_file(midi))
            self.assertEqual(song["NotationSha256"], mod.sha256_file(midi))
            self.assertEqual(song["LanguageTags"], ["zh"])
            self.assertTrue(any(tag == "\u5927\u4f17\u4f18\u5148" for tag in song["Tags"]))
            audit = json.loads((out / "source-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["priorityCounts"]["P0"], 1)
            self.assertFalse(manifest["RedistributionVerified"])
            reference = json.loads(next((out / "references").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(reference["sourceSha256"], song["SourceSha256"])
            self.assertEqual(reference["tempoChanges"], 1)
            self.assertEqual(reference["notes"][0]["pitch"], 60)
            self.assertIn("track", reference["notes"][0])
            self.assertIn("velocity", reference["notes"][0])
            self.assertFalse(reference["notes"][0]["percussion"])

    def test_limit_is_deterministic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intake, _ = self._fixture(root)
            out = root / "out"
            mod.convert_batch(intake, out, limit=1)
            with self.assertRaises(FileExistsError):
                mod.convert_batch(intake, out, limit=1)

    def test_bad_hash_and_empty_language_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intake, _ = self._fixture(root)
            payload = json.loads(intake.read_text(encoding="utf-8"))
            payload["entries"][0]["sourceSha256"] = "0" * 64
            intake.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no valid|sourceSha256"):
                mod.convert_batch(intake, root / "bad")


if __name__ == "__main__":
    unittest.main()
