"""Temporary fixtures only; never touch the real QinBan runtime or UserData."""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_popbatch_installation as checker


class DynamicInstallationFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="qinban-popbatch-check-")
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.runtime = self.dist / "QinBan-test"
        self.other_release = self.dist / "other-release"
        self.source = self.root / "repo" / "Songs"
        self.stage = self.root / "stage" / "Songs"
        self.backup = self.root / "backup"
        self.evidence = self.root / "evidence"
        self.installation_report = self.evidence / "installation.json"
        self.output = self.evidence / "check.json"
        for path in (self.runtime / "Songs", self.source, self.stage, self.backup, self.evidence, self.other_release):
            path.mkdir(parents=True, exist_ok=True)
        (self.runtime / "QinBan.exe").write_bytes(b"fixture executable")
        (self.runtime / "UserData" / "preferences.json").parent.mkdir()
        (self.runtime / "UserData" / "preferences.json").write_bytes(b"private settings")
        (self.runtime / "README.txt").write_bytes(b"release file")
        (self.source / "README.txt").write_bytes(b"source file")
        self.entries = self._entries()
        self._write_scores(self.stage, self.entries)
        self._write_catalog(self.stage, self.entries)
        old = self.entries[:2]
        self._write_scores(self.runtime / "Songs", old)
        self._write_catalog(self.runtime / "Songs", old)
        self._write_scores(self.source, old)
        self._write_catalog(self.source, old)
        shutil.copyfile(self.runtime / "Songs" / "catalog.db", self.backup / "runtime-catalog.db")
        shutil.copyfile(self.source / "catalog.db", self.backup / "source-catalog.db")
        self.runtime_before = checker.snapshot(self.runtime)
        self.source_before = checker.snapshot(self.source)
        self.distribution_before = self.evidence / "distribution-before.json"
        self.distribution_before.write_text(json.dumps({"directories": [self.runtime.name, self.other_release.name]}), encoding="utf-8")
        self._install_fixture_batch()
        self._write_installation_report()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _entries(self):
        entries = []
        for index in range(1, 6):
            if index <= 2:
                relative = f"old{index:02}.json"
                entry_id = f"builtin:{relative}"
                work_id = f"work:old-{index}"
            else:
                relative = f"pop909-{index:03}.json"
                entry_id = f"builtin:{relative}"
                work_id = f"work:new-{index}"
            score = json.dumps({"title": f"fixture {index}", "notes": [{"pitch": 60 + index, "startMs": index * 100, "durationMs": 250}]}, separators=(",", ":"), ensure_ascii=False).encode()
            metadata = json.dumps({"id": entry_id, "title": f"fixture {index}", "options": {"speed": 1, "transpose": 0}, "provenance": {"workId": work_id}}, separators=(",", ":"), ensure_ascii=False)
            entries.append({"id": entry_id, "work": work_id, "relative": relative, "score": score, "metadata": metadata})
        return entries

    @staticmethod
    def _write_scores(root: Path, entries) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            (root / entry["relative"]).write_bytes(entry["score"])

    def _write_catalog(self, root: Path, entries) -> None:
        db_path = root / "catalog.db"
        if db_path.exists():
            db_path.unlink()
        db = sqlite3.connect(db_path)
        db.executescript("""
            CREATE TABLE entries(id TEXT PRIMARY KEY, work_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL, original_hash TEXT NOT NULL, metadata_json TEXT NOT NULL);
            CREATE TABLE search_index(entry_id TEXT PRIMARY KEY, title_key TEXT NOT NULL, author_key TEXT NOT NULL,
                search_text TEXT NOT NULL, pinyin TEXT NOT NULL, initials TEXT NOT NULL, sort_title TEXT NOT NULL,
                duration REAL NOT NULL, added_ms INTEGER NOT NULL, provider TEXT NOT NULL,
                timing_verified INTEGER NOT NULL, completeness TEXT NOT NULL, human_reviewed INTEGER NOT NULL);
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        for entry in entries:
            score_hash = checker.sha(root / entry["relative"])
            db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?)", (entry["id"], entry["work"], entry["relative"], score_hash, score_hash, entry["metadata"]))
            db.execute("INSERT INTO search_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (entry["id"], entry["relative"], "fixture", entry["relative"], "fixture", "f", entry["relative"], 1.0, 1, "fixture", 1, "complete", 0))
        db.executemany("INSERT INTO meta VALUES (?,?)", [("schema", "1"), ("synthetic", "0")])
        db.commit()
        db.close()

    def _install_fixture_batch(self) -> None:
        new = self.entries[2:]
        for target in (self.runtime / "Songs", self.source):
            self._write_scores(target, new)
            shutil.copyfile(self.stage / "catalog.db", target / "catalog.db")

    def _write_installation_report(self) -> None:
        stage_catalog = checker.read_catalog(self.stage, verify_scores=True)
        new_paths = [entry["relative"] for entry in self.entries[2:]]
        report = {
            "status": "PASS", "applied": True, "preflightReady": True,
            "runtime": str(self.runtime), "source": str(self.source), "backup": str(self.backup),
            "operations": [{"target": str(self.runtime / "Songs"), "oldEntries": 2, "newEntries": 5, "newEntriesThisBatch": 3, "addFiles": new_paths}, {"target": str(self.source), "oldEntries": 2, "newEntries": 5, "newEntriesThisBatch": 3, "addFiles": new_paths}],
            "manifest": {"entries": 5, "newEntries": 3, "catalogSha256": stage_catalog.sha256, "source": str(self.stage), "scores": [{"id": key, "relativePath": value[0], "contentSha256": value[1]} for key, value in stage_catalog.entries.items()]},
            "newBuiltinCount": 3, "runtimeSnapshot": self.runtime_before, "sourceSnapshot": self.source_before,
            "actualUserDataDatabasesOpened": False, "newDistributionFolderCreated": False, "nativeKeySendAttempts": 0,
            "exeUnchanged": True, "userDataUnchanged": True,
            "after": {"runtime": checker.snapshot(self.runtime), "source": checker.snapshot(self.source)},
        }
        self.installation_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def args(self, output: Path | None = None):
        return ["--stage-songs", str(self.stage), "--installation-report", str(self.installation_report), "--runtime", str(self.runtime), "--source-songs", str(self.source), "--report", str(output or self.output), "--distribution-before", str(self.distribution_before)]
    def test_dynamic_pass_and_no_fixture_mutation(self) -> None:
        before_runtime = checker.snapshot(self.runtime)
        before_source = checker.snapshot(self.source)
        result = checker.verify_installation(stage_songs=self.stage, runtime=self.runtime, source_songs=self.source, installation_report=self.installation_report, distribution_before=self.distribution_before)
        self.assertEqual(result["status"], "PASS_INDEPENDENT_POPBATCH_INSTALLATION")
        self.assertEqual(result["counts"], {"baseline": 2, "batch": 3, "final": 5, "stageActual": 5, "runtimeActual": 5, "sourceActual": 5})
        self.assertEqual(result["newScoreFileCount"], 3)
        self.assertEqual(result["nativeKeySendAttempts"], 0)
        self.assertFalse(result["gameInputTouched"])
        self.assertEqual(checker.snapshot(self.runtime), before_runtime)
        self.assertEqual(checker.snapshot(self.source), before_source)

    def test_cli_writes_pass_report_without_overwrite(self) -> None:
        self.assertEqual(checker.main(self.args()), 0)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS_INDEPENDENT_POPBATCH_INSTALLATION")
        self.assertEqual(report["counts"]["final"], 5)
        self.assertEqual(checker.main(self.args()), 1)

    def test_changed_old_score_writes_failure_report_and_does_not_repair(self) -> None:
        old_score = self.runtime / "Songs" / "old01.json"
        original = old_score.read_bytes()
        old_score.write_bytes(original + b"changed")
        self.assertEqual(checker.main(self.args()), 1)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL_INSTALLATION_CHECK")
        self.assertIn("checksum", report["error"].lower())
        self.assertEqual(old_score.read_bytes(), original + b"changed")

    def test_preflight_report_is_rejected(self) -> None:
        report = json.loads(self.installation_report.read_text(encoding="utf-8"))
        report["status"], report["applied"] = "DRY-RUN-PASS", False
        self.installation_report.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(checker.main(self.args()), 1)
        failure = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(failure["status"], "FAIL_INSTALLATION_CHECK")
        self.assertIn("PASS/applied", failure["error"])

    def test_native_input_nonzero_is_rejected(self) -> None:
        report = json.loads(self.installation_report.read_text(encoding="utf-8"))
        report["nativeKeySendAttempts"] = 1
        self.installation_report.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(checker.main(self.args()), 1)
        failure = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertIn("nativeKeySendAttempts", failure["error"])


if __name__ == "__main__":
    unittest.main()
