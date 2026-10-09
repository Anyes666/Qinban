"""midi_lyric_corpus 候选 intake 的离线回归测试。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("acquire_midi_lyric_corpus_batch.py")
spec = importlib.util.spec_from_file_location("acquire_midi_lyric_corpus_batch", MODULE_PATH)
assert spec and spec.loader
intake = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = intake
spec.loader.exec_module(intake)


class MidiLyricCorpusBatchTests(unittest.TestCase):
    def make_source(self) -> tuple[Path, Path]:
        temporary = Path(tempfile.mkdtemp(prefix="midi-lyric-corpus-test-"))
        source = temporary / "source"
        source.mkdir()
        return temporary, source

    def write_pair(
        self,
        source: Path,
        stem: str,
        *,
        midi: bytes = b"MThd\x00\x00\x00\x06fixture-midi",
        lyrics: str | None = None,
    ) -> None:
        midi_path = source / f"{stem}.MID"
        lyrics_path = source / f"{stem}.txt"
        midi_path.parent.mkdir(parents=True, exist_ok=True)
        midi_path.write_bytes(midi)
        lyrics_path.write_text(
            lyrics
            if lyrics is not None
            else "OKPLAY Version 2.0\nLangualer=China\nPicture=\nView=\n\n测试歌曲\n作词甲/作曲乙/演唱丙\n\n春风吹过大地\n",
            encoding="utf-8",
        )

    def test_parser_uses_last_slash_segment_and_preserves_raw_artist(self) -> None:
        parsed = intake._parse_lyric_document(
            "OKPLAY Version 2.0\nLangualer=China\nPicture=\nView=\n\n"
            "测试歌曲\n作词甲/作曲乙/演唱丙\n歌词第一行\n"
        )
        self.assertEqual(parsed["title"], "测试歌曲")
        self.assertEqual(parsed["artist"], "演唱丙")
        self.assertEqual(parsed["artistRaw"], "作词甲/作曲乙/演唱丙")
        self.assertEqual(parsed["artistSegments"], ["作词甲", "作曲乙", "演唱丙"])
        self.assertEqual(parsed["headerFields"]["langualer"], "China")
        tags, basis = intake._language_tags(parsed, {"languageTags": [], "basis": []})
        self.assertEqual(tags, ["zh"])
        self.assertEqual(basis, ["txt-header:explicit-chinese-declaration"])

    def test_language_is_not_guessed_from_title(self) -> None:
        parsed = intake._parse_lyric_document(
            "英文歌名\nSinger\nThis is an English lyric only.\n"
        )
        tags, basis = intake._language_tags(parsed, {"languageTags": [], "basis": []})
        self.assertEqual(tags, [])
        self.assertEqual(basis, ["not-stated-by-lyrics-or-source"])

    def test_yue_can_come_from_explicit_header(self) -> None:
        parsed = intake._parse_lyric_document(
            "Language=Cantonese\n\n歌曲名\n作词/作曲/歌手\n歌词\n"
        )
        tags, _basis = intake._language_tags(parsed, {"languageTags": [], "basis": []})
        self.assertEqual(tags, ["yue"])

    def test_sha_ids_source_urls_and_conservative_rights(self) -> None:
        temporary, source = self.make_source()
        self.write_pair(source, "0001")
        result = intake.audit_batch(
            source,
            limit=1,
            source_url="https://example.invalid/midi_lyric_corpus",
            source_commit="fixture-commit",
            generated_at="2026-10-07T00:00:00+00:00",
        )
        entry = result["manifest"]["entries"][0]
        expected_sha = hashlib.sha256((source / "0001.MID").read_bytes()).hexdigest().upper()
        self.assertEqual(entry["sourceSha256"], expected_sha)
        self.assertTrue(entry["sourceUrl"].endswith("/blob/fixture-commit/0001.MID"))
        self.assertEqual(entry["sourceCommit"], "fixture-commit")
        self.assertTrue(entry["workId"].startswith("midi_lyric_corpus:work:"))
        self.assertTrue(entry["editionId"].startswith("midi_lyric_corpus:edition:"))
        self.assertIn("原始 MIDI+歌词版", entry["versionLabel"])
        self.assertEqual(entry["rightsStatus"], "candidate-unverified")
        self.assertFalse(entry["redistributionVerified"])
        self.assertFalse(entry["productionBuiltin"])
        self.assertFalse(entry["sourceFilesCopied"])
        self.assertEqual(result["report"]["productionSongsWritten"], 0)
        self.assertFalse(result["report"]["songsDirectoryTouched"])
        self.assertFalse(result["report"]["userDataTouched"])
        self.assertEqual(temporary.exists(), True)

    def test_duplicate_source_sha_keeps_first_deterministic_candidate(self) -> None:
        _temporary, source = self.make_source()
        self.write_pair(source, "0002", midi=b"same-midi", lyrics="歌二\n甲/乙/丙\n中文歌词\n")
        self.write_pair(source, "0001", midi=b"same-midi", lyrics="歌一\n甲/乙/丁\n中文歌词\n")
        result = intake.audit_batch(source, generated_at="2026-10-07T00:00:00+00:00")
        self.assertEqual(result["report"]["statistics"]["candidateCountBeforeLimit"], 1)
        self.assertEqual(result["report"]["statistics"]["duplicateSourceSha256Count"], 1)
        self.assertEqual(result["manifest"]["entries"][0]["sourceRelativePath"], "0001.MID")
        self.assertIn(
            "duplicate-source-sha256",
            {item["kind"] for item in result["report"]["failedItems"]},
        )

    def test_bad_pairing_records_missing_files(self) -> None:
        _temporary, source = self.make_source()
        (source / "only-midi.MID").write_bytes(b"midi")
        (source / "only-lyrics.txt").write_text("标题\n歌手\n歌词\n", encoding="utf-8")
        result = intake.audit_batch(source, generated_at="2026-10-07T00:00:00+00:00")
        self.assertEqual(result["manifest"]["entries"], [])
        self.assertEqual(result["report"]["statistics"]["pairedFileCount"], 0)
        kinds = {item["kind"] for item in result["report"]["failedItems"]}
        self.assertIn("missing-lyrics", kinds)
        self.assertIn("missing-midi", kinds)

    def test_path_escape_and_output_inside_source_are_rejected(self) -> None:
        _temporary, source = self.make_source()
        outside = source.parent / "outside.MID"
        outside.write_bytes(b"outside")
        with self.assertRaisesRegex(intake.IntakeError, "escapes source root"):
            intake._ensure_within(outside, source)
        self.write_pair(source, "0001")
        result = intake.audit_batch(source, generated_at="2026-10-07T00:00:00+00:00")
        with self.assertRaisesRegex(intake.IntakeError, "inside source root"):
            intake.write_intake(result, source / "nested-output")

    def test_output_is_new_utf8_reference_only_and_refuses_overwrite(self) -> None:
        temporary, source = self.make_source()
        self.write_pair(source, "0001")
        output = temporary / "intake-output"
        result = intake.acquire_batch(
            source,
            output,
            limit=1,
            source_url="fixture://midi_lyric_corpus",
            source_commit="fixture-commit",
            generated_at="2026-10-07T00:00:00+00:00",
        )
        self.assertEqual(
            sorted(path.name for path in output.iterdir()),
            ["README.md", "acquisition-report.json", "manifest.json", "source-audit.json"],
        )
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"][0]["rightsStatus"], "candidate-unverified")
        self.assertFalse(any(path.suffix.upper() == ".MID" for path in output.rglob("*")))
        self.assertFalse(any(path.suffix.lower() == ".txt" for path in output.rglob("*")))
        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing output"):
            intake.acquire_batch(source, output, limit=1, generated_at="2026-10-07T00:00:00+00:00")
        for path in output.iterdir():
            raw = path.read_bytes()
            raw.decode("utf-8")
        self.assertEqual(result["output"], str(output.resolve()))

    def test_negative_limit_is_rejected(self) -> None:
        _temporary, source = self.make_source()
        with self.assertRaisesRegex(intake.IntakeError, "limit must be >= 0"):
            intake.audit_batch(source, limit=-1)


if __name__ == "__main__":
    unittest.main(verbosity=2)