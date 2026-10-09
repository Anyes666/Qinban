"""Synthetic negative tests for verify_popbatch_output.py.

Every fixture is temporary and local; no repository Songs/dist/EXE/UserData/
intake/validation evidence is modified.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("verify_popbatch_output", HERE / "verify_popbatch_output.py")
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def tiny_midi():
    track = (b"\x00\xff\x51\x03\x07\xa1\x20" + b"\x00\x90\x3c\x64"
             + b"\x83\x60\x80\x3c\x64" + b"\x00\xff\x2f\x00")
    return (b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big")
            + (1).to_bytes(2, "big") + (480).to_bytes(2, "big")
            + b"MTrk" + len(track).to_bytes(4, "big") + track)


def metadata(identity, relative, payload_hash, *, work_id, edition_id, source_hash, source_url,
             smart=None, synthetic=False, music_review="not-reviewed", game_review="not-tested"):
    return {
        "id": identity, "catalogId": identity, "title": identity, "author": "fixture",
        "category": "fixture", "relativePath": relative, "hash": payload_hash,
        "resourceHash": payload_hash, "builtIn": True, "durationMs": 1000.0, "notesCount": 1,
        "bpm": 120.0, "options": {"smartInterludes": smart},
        "provenance": {
            "workId": work_id, "editionId": edition_id, "versionLabel": "fixture",
            "provider": "POP909", "sourceUrl": source_url, "sourceSha256": source_hash,
            "synthetic": synthetic, "timingStatus": "source-compared",
            "musicReview": music_review, "gameReview": game_review,
            "completeness": "unknown", "redistributionVerified": False,
        },
    }


def make_catalog(path, entries):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO meta VALUES('schema','1'),('synthetic','0');
            CREATE TABLE entries(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,original_hash TEXT NOT NULL,metadata_json TEXT NOT NULL);
            CREATE TABLE search_index(entry_id TEXT PRIMARY KEY REFERENCES entries(id),title_key TEXT NOT NULL,
                author_key TEXT NOT NULL,search_text TEXT NOT NULL,pinyin TEXT NOT NULL,initials TEXT NOT NULL,
                sort_title TEXT NOT NULL,duration REAL NOT NULL,added_ms INTEGER NOT NULL,provider TEXT NOT NULL,
                timing_verified INTEGER NOT NULL,completeness TEXT NOT NULL,human_reviewed INTEGER NOT NULL);
        """)
        for entry in entries:
            raw = copy.deepcopy({key: value for key, value in entry.items() if key != "_path"})
            prov = raw["provenance"]
            db.execute("INSERT INTO entries VALUES(?,?,?,?,?,?)", (
                raw["id"], prov["workId"], raw["relativePath"], raw["resourceHash"], raw["hash"],
                json.dumps(raw, ensure_ascii=False, indent=2)))
            db.execute("INSERT INTO search_index VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                raw["id"], raw["title"], raw["author"], raw["title"], "", "", raw["title"],
                raw["durationMs"], 0, prov["provider"], 1, prov["completeness"], 0))
        db.commit()

def make_fixture(root, *, mutate=None):
    intake, stage, baseline = root / "intake", root / "stage", root / "baseline"
    for directory in (intake, stage / "Songs", baseline):
        directory.mkdir(parents=True, exist_ok=True)
    source = intake / "song.mid"
    source.write_bytes(tiny_midi())
    source_hash = file_sha(source)
    reference = verifier.parse_smf(source.read_bytes())
    reference["sourceSha256"] = source_hash
    dump(intake / "reference.json", reference)

    old_notes = {"notes": [{"pitch": 60, "startMs": 0.0, "durationMs": 1000.0,
                             "track": 0, "velocity": 64, "percussion": False}],
                 "lengthMs": 1000.0, "bpm": 60.0}
    dump(baseline / "old.json", old_notes)
    shutil.copy2(baseline / "old.json", stage / "Songs" / "old.json")
    old_hash = file_sha(baseline / "old.json")
    old = metadata("builtin:old", "old.json", old_hash, work_id="demo:old",
                   edition_id="demo:old:v1", source_hash="A" * 64,
                   source_url="https://example/old")

    new = copy.deepcopy(reference)
    new.update({"version": 1, "title": "fixture", "author": "fixture", "category": "fixture",
                "provenance": {"workId": "demo:work", "editionId": "demo:work:v1",
                               "versionLabel": "fixture", "provider": "POP909",
                               "sourceUrl": "https://example/song", "sourceSha256": source_hash,
                               "synthetic": False, "timingStatus": "source-compared",
                               "musicReview": "not-reviewed", "gameReview": "not-tested",
                               "completeness": "unknown", "redistributionVerified": False}})
    dump(stage / "Songs" / "new.json", new)
    new_hash = file_sha(stage / "Songs" / "new.json")
    added = metadata("builtin:new", "new.json", new_hash, work_id="demo:work",
                     edition_id="demo:work:v1", source_hash=source_hash,
                     source_url="https://example/song")
    make_catalog(baseline / "catalog.db", [old])
    make_catalog(stage / "Songs" / "catalog.db", [old, added])
    dump(intake / "manifest.json", {"provider": "POP909", "songs": [{
        "id": "song", "midiPath": "song.mid", "referencePath": "reference.json",
        "sourceSha256": source_hash, "sourceUrl": "https://example/song",
        "editionId": "demo:work:v1", "workId": "demo:work", "versionLabel": "fixture"
    }]})
    if mutate:
        mutate(intake, stage, baseline, source_hash)
    return intake, stage, baseline


class PopBatchVerifierNegativeTests(unittest.TestCase):
    def run_fixture(self, mutate):
        with tempfile.TemporaryDirectory(prefix="popbatch-verifier-") as temporary:
            paths = make_fixture(Path(temporary), mutate=mutate)
            with self.assertRaises(verifier.AuditError):
                verifier.audit(*paths)

    def test_source_sha_mismatch_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            data = verifier.strict_json(intake / "manifest.json")
            data["songs"][0]["sourceSha256"] = "B" * 64
            dump(intake / "manifest.json", data)
        self.run_fixture(mutate)

    def test_normalized_note_field_mismatch_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            data = verifier.strict_json(stage / "Songs" / "new.json")
            del data["notes"][0]["velocity"]
            dump(stage / "Songs" / "new.json", data)
        self.run_fixture(mutate)

    def test_baseline_score_byte_change_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            (stage / "Songs" / "old.json").write_text("changed\n", encoding="utf-8")
        self.run_fixture(mutate)

    def test_normalized_timing_mismatch_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            data = verifier.strict_json(stage / "Songs" / "new.json")
            data["notes"][0]["startMs"] += 1.0
            dump(stage / "Songs" / "new.json", data)
        self.run_fixture(mutate)

    def test_existing_baseline_smart_interludes_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="popbatch-verifier-baseline-default-") as temporary:
            intake, stage, baseline = make_fixture(Path(temporary))
            for catalog in (baseline / "catalog.db", stage / "Songs" / "catalog.db"):
                db = sqlite3.connect(catalog)
                try:
                    row = db.execute(
                        "SELECT metadata_json FROM entries WHERE id='builtin:old'"
                    ).fetchone()
                    entry = json.loads(row[0])
                    entry["options"]["smartInterludes"] = True
                    db.execute(
                        "UPDATE entries SET metadata_json=? WHERE id='builtin:old'",
                        (json.dumps(entry),),
                    )
                    db.commit()
                finally:
                    db.close()
            result = verifier.audit(intake, stage, baseline)
            self.assertEqual(result["status"], "PASS_INDEPENDENT_POPBATCH_SOURCE_TIMING_ONLY")

    def test_non_null_smart_interludes_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            with sqlite3.connect(stage / "Songs" / "catalog.db") as db:
                row = db.execute("SELECT metadata_json FROM entries WHERE id='builtin:new'").fetchone()
                entry = json.loads(row[0])
                entry["options"]["smartInterludes"] = {"enabled": True}
                db.execute("UPDATE entries SET metadata_json=? WHERE id='builtin:new'",
                           (json.dumps(entry),))
                db.commit()
        self.run_fixture(mutate)

    def test_declared_smart_interludes_default_allows_enabled_new_entry(self):
        with tempfile.TemporaryDirectory(prefix="popbatch-verifier-") as temporary:
            intake, stage, baseline = make_fixture(Path(temporary))
            manifest = verifier.strict_json(intake / "manifest.json")
            manifest["SmartInterludesDefault"] = True
            dump(intake / "manifest.json", manifest)
            with sqlite3.connect(stage / "Songs" / "catalog.db") as db:
                row = db.execute("SELECT metadata_json FROM entries WHERE id='builtin:new'").fetchone()
                entry = json.loads(row[0])
                entry["options"]["smartInterludes"] = True
                db.execute("UPDATE entries SET metadata_json=? WHERE id='builtin:new'",
                           (json.dumps(entry),))
                db.commit()
            db.close()
            result = verifier.audit(intake, stage, baseline)
            self.assertTrue(result["smartInterludesDefault"])

    def test_synthetic_status_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            with sqlite3.connect(stage / "Songs" / "catalog.db") as db:
                row = db.execute("SELECT metadata_json FROM entries WHERE id='builtin:new'").fetchone()
                entry = json.loads(row[0])
                entry["provenance"]["synthetic"] = True
                db.execute("UPDATE entries SET metadata_json=? WHERE id='builtin:new'",
                           (json.dumps(entry),))
                db.commit()
        self.run_fixture(mutate)

    def test_duplicate_edition_id_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            with sqlite3.connect(stage / "Songs" / "catalog.db") as db:
                row = db.execute("SELECT metadata_json FROM entries WHERE id='builtin:new'").fetchone()
                entry = json.loads(row[0])
                entry["provenance"]["editionId"] = "demo:old:v1"
                db.execute("UPDATE entries SET metadata_json=? WHERE id='builtin:new'",
                           (json.dumps(entry),))
                db.commit()
        self.run_fixture(mutate)

    def test_search_index_incomplete_rejected(self):
        def mutate(intake, stage, baseline, source_hash):
            with sqlite3.connect(stage / "Songs" / "catalog.db") as db:
                db.execute("DELETE FROM search_index WHERE entry_id='builtin:new'")
                db.commit()
        self.run_fixture(mutate)

    def test_positive_fixture_reports_dynamic_counts_and_work_grouping(self):
        with tempfile.TemporaryDirectory(prefix="popbatch-verifier-") as temporary:
            result = verifier.audit(*make_fixture(Path(temporary)))
            self.assertEqual(result["status"], "PASS_INDEPENDENT_POPBATCH_SOURCE_TIMING_ONLY")
            self.assertEqual(result["baselineCount"], 1)
            self.assertEqual(result["batchCount"], 1)
            self.assertEqual(result["finalCount"], 2)
            self.assertEqual(result["uniqueNewWorks"], 1)
            self.assertIsNone(result["smartInterludesDefault"])
            self.assertTrue(result["sourceTimingOnly"])
            self.assertFalse(result["musicReview"])


if __name__ == "__main__":
    unittest.main()
