import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import validate_chinese_pop_mix as audit


class ChinesePopMixAuditTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.catalog = self.root / "Songs" / "catalog.db"
        self.catalog.parent.mkdir()
        self._create_catalog()

    def tearDown(self):
        self.tempdir.cleanup()

    def _create_catalog(self):
        connection = sqlite3.connect(self.catalog)
        connection.executescript(
            """
            CREATE TABLE entries (
                id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                original_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            """
        )
        rows = [
            self._row(
                "pop-1",
                "中文流行候选",
                "PopProvider",
                ["zh"],
                ["中文歌曲", "pop", "candidate"],
                "中文流行 · 候选",
            ),
            self._row(
                "folk-1",
                "中文民歌候选",
                "FolkProvider",
                ["cmn"],
                ["中文民歌", "folk", "candidate"],
                "中文民歌 · 候选",
            ),
            self._row(
                "english-1",
                "English pop",
                "EnglishProvider",
                ["en"],
                ["english", "pop"],
                "English pop",
            ),
            self._row(
                "bfdb-1",
                "BFDB untagged",
                "BFDB",
                [],
                ["bfdb", "folk", "candidate"],
                "BFDB candidate",
            ),
        ]
        connection.executemany(
            "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.commit()
        connection.close()

    @staticmethod
    def _row(entry_id, title, provider, languages, tags, category):
        metadata = {
            "id": entry_id,
            "title": title,
            "category": category,
            "provenance": {
                "provider": provider,
                "languageTags": languages,
                "tags": tags,
            },
        }
        blob = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        return (entry_id, f"work:{entry_id}", f"{entry_id}.json", "hash", "hash", blob)

    def _manifest(self, name, songs):
        path = self.root / name
        path.write_text(json.dumps({"songs": songs}, ensure_ascii=False), encoding="utf-8")
        return path

    def _run(self, batch, report_name="report.json", policy="chinese-pop-first", threshold=None):
        report = self.root / report_name
        args = [
            "--catalog", str(self.catalog),
            "--batch", str(batch),
            "--report", str(report),
            "--policy", policy,
        ]
        if threshold is not None:
            args += ["--max-unknown-non-chinese-ratio", str(threshold)]
        result = audit.main(args)
        data = json.loads(report.read_text(encoding="utf-8"))
        return result, data, report

    def test_chinese_candidate_passes_and_report_has_boundary(self):
        batch = self._manifest("pop.json", [{"id": "pop-1"}])
        result, report, _ = self._run(batch)
        self.assertEqual(result, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"]["batch"]["chinesePop"]["count"], 1)
        self.assertEqual(report["counts"]["batch"]["unknownPlusNonChinese"]["ratio"], 0.0)
        self.assertIn("schemaVersion", report)
        self.assertIn("generatedAtUtc", report)
        self.assertIn("catalogHash", report)
        self.assertIn("policy", report)
        self.assertIn("errors", report)
        self.assertEqual(report["sourceBoundary"]["mutations"], 0)
        self.assertIn("不是版权验收、音乐验收或游戏内验收", report["sourceBoundary"]["statement"])

    def test_catalog_stats_keep_chinese_candidate_and_unlabeled_separate(self):
        batch = self._manifest("pop.json", [{"id": "pop-1"}])
        _, report, _ = self._run(batch)
        classification = report["counts"]["catalog"]["classification"]
        self.assertEqual(classification["markedChineseCandidate"], 2)
        self.assertEqual(classification["languageTaggedChinese"], 2)
        self.assertEqual(classification["languageUnlabeled"], 1)
        self.assertEqual(report["counts"]["catalog"]["provider"]["BFDB"], 1)
        self.assertEqual(report["counts"]["catalog"]["languageTags"]["zh"], 1)
        self.assertEqual(report["counts"]["catalog"]["category"]["中文民歌 · 候选"], 1)

    def test_all_bfdb_without_language_tag_is_unknown_and_fails(self):
        batch = self._manifest("bfdb.json", [{"id": "bfdb-1"}])
        result, report, _ = self._run(batch)
        self.assertNotEqual(result, 0)
        self.assertEqual(report["counts"]["batch"]["unknown"]["count"], 1)
        self.assertEqual(report["counts"]["batch"]["nonChinese"]["count"], 0)
        self.assertTrue(any("没有中文流行候选" in error for error in report["errors"]))

    def test_folk_and_english_are_not_chinese_pop(self):
        batch = self._manifest("mixed.json", [{"id": "folk-1"}, {"id": "english-1"}])
        result, report, _ = self._run(batch)
        self.assertNotEqual(result, 0)
        counts = report["counts"]["batch"]
        self.assertEqual(counts["chinesePop"]["count"], 0)
        self.assertEqual(counts["chineseFolk"]["count"], 1)
        self.assertEqual(counts["nonChinese"]["count"], 1)
        self.assertEqual(counts["unknown"]["count"], 0)

    def test_empty_batch_fails(self):
        batch = self._manifest("empty.json", [])
        result, report, _ = self._run(batch)
        self.assertNotEqual(result, 0)
        self.assertEqual(report["counts"]["batch"]["total"], 0)
        self.assertTrue(any("批次为空" in error for error in report["errors"]))

    def test_ratio_threshold_is_configurable(self):
        batch = self._manifest("ratio.json", [{"id": "pop-1"}, {"id": "bfdb-1"}])
        result, report, _ = self._run(batch, threshold=0.5)
        self.assertEqual(result, 0)
        self.assertEqual(report["counts"]["batch"]["unknownPlusNonChinese"]["ratio"], 0.5)
        result, report, _ = self._run(batch, report_name="ratio-fail.json", threshold=0.49)
        self.assertNotEqual(result, 0)
        self.assertTrue(any("超过阈值" in error for error in report["errors"]))

    def test_catalog_hash_and_report_refuse_overwrite(self):
        batch = self._manifest("pop.json", [{"id": "pop-1"}])
        result, report, report_path = self._run(batch)
        self.assertEqual(result, 0)
        expected_hash = hashlib.sha256(self.catalog.read_bytes()).hexdigest().upper()
        self.assertEqual(report["catalogHash"], expected_hash)

        report_path.write_text("sentinel", encoding="utf-8")
        result = audit.main([
            "--catalog", str(self.catalog),
            "--batch", str(batch),
            "--report", str(report_path),
            "--policy", "chinese-pop-first",
        ])
        self.assertNotEqual(result, 0)
        self.assertEqual(report_path.read_text(encoding="utf-8"), "sentinel")


if __name__ == "__main__":
    unittest.main()