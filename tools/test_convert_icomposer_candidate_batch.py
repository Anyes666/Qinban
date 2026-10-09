import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("convert_icomposer_candidate_batch.py")
spec = importlib.util.spec_from_file_location("convert_icomposer_candidate_batch", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IComposerConverterTests(unittest.TestCase):
    def refs(self, root: Path) -> Path:
        payload = {
            "schemaVersion": "fixture",
            "entries": [{
                "WorkId": "icomposer-fixture-work",
                "EditionId": "icomposer-fixture-edition",
                "SourceSha256": "A" * 64,
                "SourceUrl": "fixture://note/test.txt",
                "Source": {"noteDownloadSha256": "A" * 64},
                "Notes": [
                    {"start": 0, "duration": 0.5, "pitches": [60], "lyric": "a"},
                    {"start": 0.5, "duration": 0.25, "pitches": [64, 67], "lyric": "b"},
                ],
                "TotalDuration": 0.75,
            }],
        }
        path = root / "references.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_converts_midi_reference_manifest_without_production_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = self.refs(root)
            out = root / "out"
            result = mod.convert_batch(refs, out, source_commit="c" * 40, retrieved_at="2026-10-07T00:00:00Z", archive_sha256="B" * 64)
            self.assertEqual(result["count"], 1)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            song = manifest["Songs"][0]
            self.assertFalse(manifest["RedistributionVerified"])
            self.assertEqual(song["LanguageTags"], [])
            self.assertFalse((out / "source-audit.json").exists() is False)
            midi = Path(song["MidiPath"])
            reference = Path(song["ReferencePath"])
            self.assertTrue(midi.is_file())
            self.assertEqual(midi.read_bytes()[:4], b"MThd")
            self.assertEqual(song["NotationSha256"], mod.sha256_file(midi))
            self.assertNotEqual(song["NotationSha256"], mod.sha256_file(reference))
            ref = json.loads(reference.read_text(encoding="utf-8"))
            self.assertEqual(len(ref["notes"]), 3)
            self.assertEqual(ref["lengthMs"], 750.0)
            self.assertEqual(ref["bpm"], mod.BPM_ANCHOR)
            self.assertEqual(ref["tempoChanges"], 1)
            self.assertEqual(ref["sourceSha256"], song["NotationSha256"])
            self.assertEqual(ref["notes"][0]["track"], 0)
            self.assertEqual(ref["notes"][0]["velocity"], 88)
            self.assertFalse(ref["notes"][0]["percussion"])

    def test_rejects_empty_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "references.json"
            path.write_text(json.dumps({"entries": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                mod.convert_batch(path, root / "out", source_commit="c" * 40, retrieved_at="2026-10-07T00:00:00Z")

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = self.refs(root)
            out = root / "out"
            mod.convert_batch(refs, out, source_commit="c" * 40, retrieved_at="2026-10-07T00:00:00Z")
            with self.assertRaises(FileExistsError):
                mod.convert_batch(refs, out, source_commit="c" * 40, retrieved_at="2026-10-07T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
