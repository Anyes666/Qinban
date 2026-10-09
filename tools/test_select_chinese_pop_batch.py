import hashlib, json, tempfile, unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path
from tools import select_chinese_pop_batch as gate


class ChinesePopPriorityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("scores", "evidence", "rights", "charts"):
            (self.root / name).mkdir()
        self.as_of = date(2026, 10, 7)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, rel, value):
        path = self.root / rel
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest().upper()

    def candidate(self, name="s1", artist="歌手甲", work="w1", edition="e1", released="2025-01-02", rank=1):
        title = "热歌-" + name
        midi = self.root / "scores" / (name + ".mid")
        midi.write_bytes(b"MThd:" + name.encode())
        midi_hash = hashlib.sha256(midi.read_bytes()).hexdigest().upper()
        ident_snapshot = {"title": title, "artist": artist, "languageTags": ["zh"], "workId": work,
                          "editionId": edition, "versionLabel": "\u539f\u5531\u5f55\u97f3\u5ba4\u7248", "releaseDate": released}
        ident_snapshot_path = f"evidence/{name}-identity-source.json"
        ident_snapshot_hash = self.write_json(ident_snapshot_path, ident_snapshot)
        ident = {"status": "verified", **ident_snapshot, "sourceUrl": "https://music.163.com/song?id=123",
                 "sourceArtifact": {"path": ident_snapshot_path, "sha256": ident_snapshot_hash}}
        ident_hash = self.write_json(f"evidence/{name}-identity.json", ident)
        rights_snapshot_path = f"rights/{name}-grant-source.json"
        rights_snapshot_hash = self.write_json(rights_snapshot_path, {"grant": "desktop adaptation and redistribution"})
        rights = {"status": "verified", "workId": work, "editionId": edition,
                  "licenseId": "grant-001", "scope": {"adaptation": True, "desktopSoftwareRedistribution": True},
                  "grantSourceUrl": "https://rights.example.org/grant/001", "reviewedAt": "2026-10-01", "reviewer": "auditor-1",
                  "sourceArtifact": {"path": rights_snapshot_path, "sha256": rights_snapshot_hash}}
        rights_hash = self.write_json(f"rights/{name}-grant.json", rights)
        url = "https://www.douyin.com/music/collection/1"
        chart_snapshot_path = f"charts/{name}-douyin-source.json"
        chart_snapshot_hash = self.write_json(chart_snapshot_path, {"page": "official chart snapshot", "title": title, "artist": artist, "rank": rank})
        chart = {"platform": "douyin", "rank": rank, "observedAt": "2026-10-05", "title": title, "artist": artist, "sourceUrl": url,
                 "sourceArtifact": {"path": chart_snapshot_path, "sha256": chart_snapshot_hash}}
        chart_hash = self.write_json(f"charts/{name}-douyin.json", chart)
        return {"id": name, "title": title, "artist": artist, "artists": [artist], "languageTags": ["zh"],
                "languageStatus": "verified", "workId": work, "editionId": edition, "versionLabel": "原唱录音室版",
                "releaseDate": released, "midiPath": str(midi), "sourceSha256": midi_hash,
                "identityEvidence": {"path": f"evidence/{name}-identity.json", "sha256": ident_hash},
                "redistributionVerified": True, "adaptationAllowed": True,
                "rightsEvidence": {"path": f"rights/{name}-grant.json", "sha256": rights_hash},
                "chartEvidence": [{"platform": "douyin", "rank": rank, "observedAt": "2026-10-05", "sourceUrl": url,
                                   "evidence": {"path": f"charts/{name}-douyin.json", "sha256": chart_hash}}]}

    @staticmethod
    def empty_installed():
        return {"sourceHashes": set(), "editionIds": set()}

    def test_full_evidence_candidate_passes(self):
        row = self.candidate()
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["counts"]["selected"], 1)
        self.assertEqual(report["selectedCandidates"][0]["editionId"], "e1")

    def test_unlicensed_candidate_fails_even_when_editorial_p0(self):
        row = self.candidate()
        row.update({"priority": True, "redistributionVerified": False, "adaptationAllowed": False})
        row.pop("rightsEvidence")
        row.pop("identityEvidence")
        row["chartEvidence"] = []
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        reasons = set(report["rejectedCandidates"][0]["rejectionReasons"])
        self.assertEqual(report["counts"]["selected"], 0)
        self.assertIn("redistribution_not_verified", reasons)
        self.assertIn("adaptation_not_verified", reasons)
        self.assertIn("no_fresh_verified_official_chart_evidence", reasons)

    def test_source_hash_mismatch_fails(self):
        row = self.candidate()
        row["sourceSha256"] = "0" * 64
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("source_sha256_mismatch", report["rejectedCandidates"][0]["rejectionReasons"])

    def test_source_path_escape_fails(self):
        row = self.candidate()
        outside = self.root.parent / "outside.mid"
        outside.write_bytes(b"MThd")
        row["midiPath"] = str(outside)
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("source_path_outside_root", report["rejectedCandidates"][0]["rejectionReasons"])
        outside.unlink()

    def test_identity_evidence_mismatch_fails(self):
        row = self.candidate()
        ident_path = row["identityEvidence"]["path"]
        ident = json.loads((self.root / ident_path).read_text(encoding="utf-8"))
        ident["artist"] = "错误歌手"
        row["identityEvidence"]["sha256"] = self.write_json(ident_path, ident)
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("identity_artist_mismatch", report["rejectedCandidates"][0]["rejectionReasons"])

    def test_non_chinese_language_fails(self):
        row = self.candidate()
        row["languageTags"] = ["en"]
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("chinese_language_not_verified", report["rejectedCandidates"][0]["rejectionReasons"])

    def test_no_recent_release_is_held(self):
        row = self.candidate(released="2012-01-01")
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertEqual(report["status"], "HOLD_RECENT_DIVERSITY")
        self.assertEqual(report["counts"]["selected"], 0)

    def test_per_work_cap_keeps_two_distinct_editions(self):
        rows = [self.candidate(f"v{i}", artist=f"歌手{i}", work="same-work", edition=f"ed{i}") for i in range(3)]
        report = gate.select_batch(rows, self.root, self.as_of, limit=3, recent_share=0, max_per_work=2, installed=self.empty_installed())
        self.assertEqual(report["counts"]["selected"], 2)
        self.assertEqual(report["status"], "PARTIAL_READY")

    def test_artist_cap_limits_single_artist(self):
        rows = [self.candidate("a1", "同一歌手", "w1", "e1"), self.candidate("a2", "同一歌手", "w2", "e2"),
                self.candidate("b1", "另一歌手", "w3", "e3")]
        report = gate.select_batch(rows, self.root, self.as_of, limit=3, recent_share=0, max_per_artist=1, installed=self.empty_installed())
        self.assertEqual(report["counts"]["selected"], 2)
        self.assertEqual(len({x["artist"] for x in report["selectedCandidates"]}), 2)

    def test_installed_hash_is_not_counted_again(self):
        row = self.candidate()
        installed = {"sourceHashes": {row["sourceSha256"]}, "editionIds": set()}
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=installed)
        self.assertIn("source_already_in_catalog", report["rejectedCandidates"][0]["rejectionReasons"])

    def test_identity_ledger_without_source_snapshot_fails(self):
        row = self.candidate()
        rel = row["identityEvidence"]["path"]
        ident = json.loads((self.root / rel).read_text(encoding="utf-8"))
        ident.pop("sourceArtifact")
        row["identityEvidence"]["sha256"] = self.write_json(rel, ident)
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("evidence_source_artifact_missing", report["rejectedCandidates"][0]["rejectionReasons"])

    def test_chart_snapshot_hash_mismatch_fails(self):
        row = self.candidate()
        (self.root / "charts/s1-douyin-source.json").write_text("{\"edited\":true}", encoding="utf-8")
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        reasons = report["rejectedCandidates"][0]["rejectionReasons"]
        self.assertIn("no_fresh_verified_official_chart_evidence", reasons)
        self.assertTrue(any("source_artifact_hash_mismatch" in value for value in reasons))

    def test_recent_edition_is_reserved_before_older_same_artist(self):
        old = self.candidate("old", "same-artist", "w-old", "ed-old", released="2012-01-01", rank=1)
        recent = self.candidate("recent", "same-artist", "w-new", "ed-new", released="2025-01-01", rank=2)
        report = gate.select_batch([old, recent], self.root, self.as_of, limit=1, max_per_artist=1, installed=self.empty_installed())
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["selectedCandidates"][0]["id"], "recent")

    def test_missing_chart_evidence_fails(self):
        row = self.candidate()
        row["chartEvidence"] = []
        report = gate.select_batch([row], self.root, self.as_of, limit=1, installed=self.empty_installed())
        self.assertIn("no_fresh_verified_official_chart_evidence", report["rejectedCandidates"][0]["rejectionReasons"])


    def test_manifest_byte_limit_rejects_before_read(self):
        path = self.root / "large.json"
        path.write_bytes(b"[]" + b" " * 30)
        with patch.object(Path, "open", side_effect=AssertionError("must not read")):
            with self.assertRaises(gate.InputLimitError):
                gate.load_manifest(path, max_bytes=8)

    def test_manifest_candidate_limit(self):
        path = self.root / "many.json"
        path.write_text(json.dumps([{}, {}, {}]), encoding="utf-8")
        with self.assertRaises(gate.InputLimitError):
            gate.load_manifest(path, max_candidates=2)

    def test_small_manifest_under_limits(self):
        path = self.root / "small.json"
        path.write_text('{"candidates": [{"title": "song"}]}', encoding="utf-8")
        self.assertEqual(gate.load_manifest(path, max_candidates=1)[0]["title"], "song")

    def cli_args(self, manifest, report):
        return ["--manifest", str(manifest), "--root", str(self.root),
                "--as-of", "2026-10-08", "--report", str(report)]

    def test_cli_combined_candidates_fail_without_output(self):
        first, second = self.root / "first.json", self.root / "second.json"
        first.write_text('[{}, {}]', encoding="utf-8")
        second.write_text('[{}]', encoding="utf-8")
        report = self.root / "new" / "report.json"
        result = gate.main(self.cli_args(first, report) + ["--manifest", str(second), "--max-candidates", "2"])
        self.assertEqual(result, 2)
        self.assertFalse(report.parent.exists())

    def test_cli_combined_manifest_bytes_fail_without_output(self):
        first, second = self.root / "first.json", self.root / "second.json"
        for path in (first, second):
            path.write_bytes(b"[]" + b" " * (600 * 1024))
        report = self.root / "new" / "report.json"
        result = gate.main(self.cli_args(first, report) + ["--manifest", str(second), "--max-input-mib", "1"])
        self.assertEqual(result, 2)
        self.assertFalse(report.parent.exists())

    def test_cli_report_limit_fail_without_output(self):
        manifest = self.root / "input.json"
        manifest.write_text('[]', encoding="utf-8")
        report = self.root / "new" / "report.json"
        with patch.object(gate, "select_batch", return_value={"blob": "x" * (2 * gate.MIB)}):
            result = gate.main(self.cli_args(manifest, report) + ["--max-report-mib", "1"])
        self.assertEqual(result, 2)
        self.assertFalse(report.parent.exists())

    def test_cli_default_limit_and_existing_output_are_safe(self):
        manifest = self.root / "input.json"
        manifest.write_text('[]', encoding="utf-8")
        report = self.root / "report.json"
        self.assertEqual(gate.main(self.cli_args(manifest, report)), 0)
        raw = report.read_bytes()
        self.assertEqual(json.loads(raw)["resourceLimits"]["batchLimit"], 20)
        self.assertEqual(gate.main(self.cli_args(manifest, report)), 2)
        self.assertEqual(report.read_bytes(), raw)

    def test_nonpositive_resource_limit_fails(self):
        manifest = self.root / "input.json"
        manifest.write_text('[]', encoding="utf-8")
        report = self.root / "report.json"
        self.assertEqual(gate.main(self.cli_args(manifest, report) + ["--max-candidates", "0"]), 2)
        self.assertFalse(report.exists())

    def test_oversized_evidence_is_rejected_before_hash(self):
        row = self.candidate()
        with patch.object(gate, "MAX_JSON_BYTES", 1), patch.object(gate, "digest", side_effect=AssertionError("must not hash")):
            value, error = gate.evidence(self.root, row["identityEvidence"])
        self.assertIsNone(value)
        self.assertEqual(error, "evidence_json_exceeds_byte_limit")

    def test_oversized_evidence_has_explicit_rejection(self):
        row = self.candidate()
        with patch.object(gate, "MAX_JSON_BYTES", 1):
            # The helper's explicit argument enforces the patched test limit.
            original = gate.read_json_bounded
            with patch.object(gate, "read_json_bounded", side_effect=lambda p: original(p, 1)):
                value, error = gate.evidence(self.root, row["identityEvidence"])
        self.assertIsNone(value)
        self.assertEqual(error, "evidence_json_exceeds_byte_limit")


if __name__ == "__main__":
    unittest.main()
