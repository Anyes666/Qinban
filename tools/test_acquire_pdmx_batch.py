"""Independent regression tests for acquire_pdmx_batch.py.

These tests inspect only the intake helper and its isolated evidence output. They
never invoke the product runtime, a game process, native input, or elevation.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import acquire_pdmx_batch as intake  # noqa: E402


REAL_OUTPUT = ROOT / "catalog-intake" / "pdmx-2026-10-06" / "batch-100-2026-10-06-final-verified"


TOP_LEVEL_FIELDS = {
    "Songs", "SourceCommit", "SourceRecord", "RetrievedAtUtc", "Provider", "BatchKind", "SourceUrl",
    "License", "LicenseUrl", "RightsStatus", "RightsNote", "RedistributionVerified", "Author", "Category",
    "Description", "IdPattern", "SmartInterludesDefault",
}
SONG_FIELDS = {
    "Id", "Title", "Artist", "MidiPath", "ReferencePath", "SourceUrl", "SourceSha256", "LanguageTags",
    "Artists", "Provider", "SourceCommit", "SourceRecord", "BatchKind", "Author", "Category", "Description",
    "IdPattern", "SmartInterludes", "WorkId", "EditionId", "VersionLabel", "License", "LicenseUrl",
    "RightsStatus", "RightsNote", "Album", "Aliases", "Tags", "Completeness", "MusicReview", "GameReview",
    "RedistributionVerified",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def minimal_item() -> dict[str, object]:
    return {
        "id": "pdmx-QmExample", "title": "Example", "songName": "Example", "artist": "Artist", "composer": "Composer",
        "workId": "pdmx-work:example::composer", "editionId": "pdmx:15571083:QmExample", "versionLabel": "PDMX score 1",
        "sourceFields": {"license": "publicdomain", "license_url": "https://creativecommons.org/publicdomain/mark/1.0/"},
        "midiPath": str(ROOT / "x.mid"), "referencePath": str(ROOT / "x.json"), "sourceUrl": "https://musescore.com/scores/1",
        "sourceSha256": "A" * 64, "languageTags": [], "metadataSource": intake.ZENODO_RECORD_URL,
        "sourcePath": "data/1/1/QmExample.json", "sourceMidiPath": "mid/1/1/QmExample.mid", "sourceMetadataPath": "metadata/1/1.json",
        "metadataRecordPath": str(ROOT / "metadata-record.json"), "durationMs": 100000.0, "sourceDurationSeconds": 100.0,
        "notes": 100, "tempoChanges": 1, "durationKinds": 2, "completeness": "source-all_valid", "musicReview": "not-reviewed",
        "gameReview": "not-tested", "redistributionVerified": False, "rightsNote": "candidate", "rightsStatus": "candidate-unverified",
        "publicationStatus": "blocked-pending-manual-rights-review", "modernWorkAutoPublication": False,
    }


class AcquirePdmxBatchTests(unittest.TestCase):
    def test_contract_manifest_contains_only_contract_fields(self) -> None:
        manifest = intake._contract_manifest([minimal_item()], "2026-10-06T00:00:00+00:00")
        self.assertEqual(set(manifest), TOP_LEVEL_FIELDS)
        self.assertEqual(set(manifest["Songs"][0]), SONG_FIELDS)
        self.assertNotIn("composer", manifest["Songs"][0])
        self.assertNotIn("sourceFields", manifest["Songs"][0])

    def test_contract_manifest_declares_smart_interludes_default(self) -> None:
        manifest = intake._contract_manifest([minimal_item()], "2026-10-06T00:00:00+00:00")
        self.assertTrue(manifest["SmartInterludesDefault"])
        self.assertTrue(manifest["Songs"][0]["SmartInterludes"])

    def test_existing_manifest_dedupe_keeps_new_edition_for_same_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pdmx-intake-index-") as temporary:
            root = Path(temporary)
            manifest = {
                "Provider": "PDMX",
                "Songs": [{
                    "Id": "pdmx-existing",
                    "SourceSha256": "A" * 64,
                    "WorkId": "pdmx-work:example::composer",
                    "EditionId": "pdmx:15571083:Existing",
                    "VersionLabel": "existing edition",
                }],
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            index = intake._load_existing_manifest_index(path)
            same_work_new_edition = {
                "row": {"title": "Example", "song_name": "Example", "composer_name": "Composer", "metadata": "metadata/1/2.json"},
                "metadataSummary": {"fields": {"score_id": 2, "instruments": []}},
                "midPath": "mid/1/2/QmNew.mid",
                "sourceSha256": "B" * 64,
            }
            rejected = []
            kept = intake._filter_candidates_against_existing([same_work_new_edition], index, rejected)
            self.assertEqual(len(kept), 1)
            self.assertEqual(rejected, [])
            self.assertTrue(kept[0]["batchDeduplication"]["sameWorkIdAlreadyInExisting"])
            duplicate_source = dict(same_work_new_edition)
            duplicate_source["sourceSha256"] = "A" * 64
            rejected = []
            self.assertEqual(intake._filter_candidates_against_existing([duplicate_source], index, rejected), [])
            self.assertEqual(rejected[0]["reason"], "source SHA256 already exists in prior intake")

    def test_select_batch_uses_deterministic_offset(self) -> None:
        candidates = [{"id": str(index)} for index in range(5)]
        selected = intake._select_batch(candidates, offset=2, limit=2)
        self.assertEqual([item["id"] for item in selected], ["2", "3"])
        with self.assertRaises(intake.IntakeError):
            intake._select_batch(candidates, offset=4, limit=2)

    def test_runtime_title_is_bounded_without_discarding_source_value(self) -> None:
        bounded, truncated = intake._bounded_core_title("X" * 200)
        self.assertEqual(len(bounded), intake.CORE_TITLE_LIMIT)
        self.assertTrue(truncated)
        self.assertTrue(bounded.endswith("..."))
        short, short_truncated = intake._bounded_core_title("Short title")
        self.assertEqual(short, "Short title")
        self.assertFalse(short_truncated)

    def test_duplicate_display_titles_get_edition_suffix_without_changing_identity(self) -> None:
        items = [
            {
                "id": "pdmx-first", "title": "Si Bheag Si Mhor", "artist": "Misc tunes",
                "workId": "pdmx-work:si-bheag-si-mhor::composer-a",
                "editionId": "pdmx:15571083:first",
                "versionLabel": "PDMX score 4570245 / source title: Si Bheag Si Mhor",
                "_metadataDocument": {"derived": {"displayTitle": "Si Bheag Si Mhor"}},
            },
            {
                "id": "pdmx-second", "title": "Si Bheag Si Mhor", "artist": "Misc tunes",
                "workId": "pdmx-work:si-bheag-si-mhor::misc-tunes",
                "editionId": "pdmx:15571083:second",
                "versionLabel": "PDMX score 4602040 / source title: Si Bheag Si Mhor",
                "_metadataDocument": {"derived": {"displayTitle": "Si Bheag Si Mhor"}},
            },
        ]
        intake._disambiguate_duplicate_display_titles(items)
        self.assertEqual({item["title"] for item in items}, {"Si Bheag Si Mhor (PDMX score 4570245)", "Si Bheag Si Mhor (PDMX score 4602040)"})
        self.assertEqual(items[0]["workId"], "pdmx-work:si-bheag-si-mhor::composer-a")
        self.assertEqual(items[1]["editionId"], "pdmx:15571083:second")
        self.assertEqual(items[0]["_metadataDocument"]["derived"]["displayTitle"], items[0]["title"])
        self.assertTrue(items[0]["_metadataDocument"]["derived"]["displayTitleDisambiguation"]["workIdUnchanged"])

    def test_source_path_rejects_traversal_and_absolute_paths(self) -> None:
        with self.assertRaises(intake.IntakeError):
            intake._safe_source_path("../mid/evil.mid", suffix=".mid")
        with self.assertRaises(intake.IntakeError):
            intake._safe_source_path("C:/outside.mid", suffix=".mid")
        self.assertEqual(intake._safe_source_path("./mid/1/2/song.mid", suffix=".mid"), "mid/1/2/song.mid")

    def test_suspicious_encoding_and_modern_signals_are_flagged(self) -> None:
        self.assertTrue(intake._has_suspicious_text("DvoÅák"))
        signals = intake._modern_rights_signals({"title": "", "song_name": "", "artist_name": "Miku Hatsune", "composer_name": "", "genres": "", "tags": ""})
        self.assertIn("modern-popular-text", signals)

    def test_metadata_false_public_domain_and_missing_score_url_are_rejected(self) -> None:
        row = {
            "title": "Example", "song_name": "Example", "artist_name": "Artist", "composer_name": "Composer",
            "license": "publicdomain", "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
        }
        payload = {
            "data": {
                "is_public_domain": False,
                "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
                "score": {"id": 123, "title": "Example", "song_name": "Example", "artist_name": "Artist", "composer_name": "Composer", "license": "publicdomain", "url": ""},
            }
        }
        summary, errors = intake._validate_metadata(row, payload, "metadata/1/123.json")
        self.assertEqual(summary["validation"]["status"], "REJECT")
        self.assertIn("metadata_is_public_domain_not_true", errors)
        self.assertIn("metadata_score_url_missing_or_not_http", errors)

    def test_real_output_is_contract_clean_and_hash_bound(self) -> None:
        self.assertTrue(REAL_OUTPUT.is_dir(), REAL_OUTPUT)
        manifest_path = REAL_OUTPUT / "manifest.json"
        build_path = REAL_OUTPUT / "build-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        build_manifest = json.loads(build_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_manifest)
        self.assertEqual(set(manifest), TOP_LEVEL_FIELDS)
        self.assertEqual(len(manifest["Songs"]), 100)
        for song in manifest["Songs"]:
            self.assertEqual(set(song), SONG_FIELDS)
            self.assertFalse(song["RedistributionVerified"])
            self.assertEqual(song["RightsStatus"], "candidate-unverified")
            self.assertEqual(song["MusicReview"], "not-reviewed")
            self.assertEqual(song["GameReview"], "not-tested")
            self.assertEqual(sha256(Path(song["MidiPath"])), song["SourceSha256"])
            self.assertTrue(Path(song["ReferencePath"]).is_file())
        self.assertEqual(len(list((REAL_OUTPUT / "midi").glob("*.mid"))), 100)
        self.assertEqual(len(list((REAL_OUTPUT / "references").glob("*.json"))), 100)
        self.assertEqual(len(list((REAL_OUTPUT / "metadata" / "records").glob("*.json"))), 100)
        report = json.loads((REAL_OUTPUT / "acquisition-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS_PDMX_METADATA_FIRST_BATCH")
        self.assertEqual(report["selectedCount"], 100)
        self.assertFalse(report["eligibleForProductInstall"])
        self.assertGreater(report["rejectedCount"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

