"""Adversarial regression tests for the provider-agnostic add-only updater.

All inputs in this module are disposable, synthetic fixtures.  The tests never
open the real Songs/UserData folders, execute QinBan.exe, send keys, elevate,
kill processes, or alter a real runtime.  The fixture deliberately resembles
the updater contract closely enough to exercise its guards, including a 601
entry delta, but it is not evidence for any musical source or redistribution
right.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
import update_popbatch_library as update  # noqa: E402


UNSET = object()


def digest(data):
    return hashlib.sha256(data).hexdigest().upper()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def title_key(value):
    return " ".join(value.casefold().split())


def pascal_manifest(lower_manifest, *, midi_paths=None):
    """Convert the fixture manifest to the PopBatchTool v2 field casing."""
    songs = []
    for index, item in enumerate(lower_manifest["songs"]):
        song = {
            "Id": item["id"],
            "Title": item.get("title"),
            "WorkId": item["workId"],
            "EditionId": item["editionId"],
            "VersionLabel": item["versionLabel"],
            "SourceUrl": item["sourceUrl"],
            "SourceSha256": item["sourceSha256"],
            "ReferencePath": f"references/{item['id']}.json",
        }
        if midi_paths is not None:
            song["MidiPath"] = midi_paths[index]
        songs.append(song)
    return {"Provider": lower_manifest["provider"], "Songs": songs}


class DisposableFixture:
    """A complete isolated workspace accepted by update_popbatch_library."""

    def __init__(self, baseline_count=3, batch_count=4, *, provider="POP909",
                 batch_prefix=None, write_manifest=False):
        self.temp = tempfile.TemporaryDirectory(prefix="qinban-popbatch-adversarial-")
        self.workspace = Path(self.temp.name).resolve()
        self.runtime = self.workspace / "dist" / "fixture-runtime"
        self.source = self.workspace / "repo" / "Songs"
        self.stage = self.workspace / "stage" / "Songs"
        self.backup = self.workspace / "evidence" / "backup"
        self.report = self.workspace / "evidence" / "report.json"
        self.baseline_count = baseline_count
        self.batch_count = batch_count
        self.provider = provider
        self.batch_prefix = batch_prefix or provider.casefold()
        self.write_manifest = write_manifest
        self.manifest_path = self.stage.parent / "input-manifest.json"
        self.old_rows = []
        self.new_rows = []
        self.old_metadata = {}
        self.new_metadata = {}
        self.old_scores = {}
        self.new_scores = {}

        for path in (self.runtime / "Songs", self.source, self.stage):
            path.mkdir(parents=True, exist_ok=True)
        self.backup.parent.mkdir(parents=True, exist_ok=True)

        resources = {
            "QinBan.exe": b"FAKE FIXTURE EXE; NEVER EXECUTED",
            "UserData/library.db": b"fixture hash only; never opened as sqlite",
            "UserData/preferences.json": b"private fixture preferences",
            "UserData/backgrounds/private.bin": b"private fixture background",
            "QINBAN-NOTICES.md": b"fixture notice",
        }
        for relative, data in resources.items():
            path = self.runtime / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.runtime / "UserData" / "empty").mkdir()

        (self.source / "private-extra.txt").write_bytes(b"uncatalogued source fixture file")
        (self.source / "nested").mkdir()
        (self.source / "nested" / "keep.txt").write_bytes(b"preserve source tree")

        self._populate()

    def close(self):
        root = self.workspace
        if root != Path(self.temp.name).resolve() or not root.name.startswith("qinban-popbatch-adversarial-"):
            raise AssertionError("unexpected disposable fixture cleanup target")
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                except FileNotFoundError:
                    pass
        self.temp.cleanup()

    def _provenance(self, *, provider, work_id, edition_id, source_hash, version_label=""):
        return {
            "provider": provider,
            "workId": work_id,
            "editionId": edition_id,
            "versionLabel": version_label,
            "artists": ["Fixture Artist"],
            "sourceUrl": "fixture://source",
            "sourceSha256": source_hash,
            "synthetic": True,
            "redistributionVerified": False,
            "musicReview": "not-reviewed",
            "gameReview": "not-tested",
            "timingStatus": "fixture-only",
        }

    def _batch_relative(self, sid):
        return f"{self.batch_prefix}-{sid:03}.json"

    def _new_provenance(self, sid):
        source_hash = digest(f"fake {self.provider} source bytes {sid:03}".encode("ascii"))
        return {
            "provider": self.provider,
            "workId": f"{self.batch_prefix}:{sid:03}",
            "editionId": f"{self.batch_prefix}-edition:{sid:03}",
            "versionLabel": "",
            "artists": [f"Fixture Artist {sid:03}"],
            "sourceUrl": f"fixture://{self.batch_prefix}/{sid:03}.mid",
            "sourceSha256": source_hash,
            "synthetic": False,
            "redistributionVerified": False,
            "musicReview": "not-reviewed",
            "gameReview": "not-tested",
            "timingStatus": "source-compared",
        }

    def _populate(self):
        for index in range(1, self.baseline_count + 1):
            relative = f"old-{index:03}.json"
            score = {
                "title": f"Baseline fixture title {index:03}",
                "provenance": self._provenance(
                    provider="fixture",
                    work_id=f"baseline-work:{index:03}",
                    edition_id=f"baseline-edition:{index:03}",
                    source_hash=digest(f"baseline-source-{index}".encode("ascii")),
                ),
                "notes": [],
                "fixtureOnly": True,
            }
            data = json_bytes(score)
            (self.stage / relative).write_bytes(data)
            metadata = {
                "id": f"builtin:{relative}",
                "catalogId": f"builtin:{relative}",
                "title": score["title"],
                "provenance": score["provenance"],
                "options": {"tracks": [1], "speed": 1, "transpose": 0},
                "fixtureOnly": True,
            }
            row = (
                f"builtin:{relative}",
                score["provenance"]["workId"],
                relative,
                digest(data),
                score["provenance"]["sourceSha256"],
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            )
            self.old_rows.append(row)
            self.old_metadata[row[0]] = metadata
            self.old_scores[row[0]] = data

        for sid in range(1, self.batch_count + 1):
            relative = self._batch_relative(sid)
            entry_id = f"builtin:{relative}"
            provenance = self._new_provenance(sid)
            score = {
                "title": f"Batch fixture title {sid:03}",
                "provenance": provenance,
                "notes": [{"pitch": 60, "startMs": 0, "durationMs": 500}],
                "fixtureOnly": True,
            }
            data = json_bytes(score)
            (self.stage / relative).write_bytes(data)
            metadata = {
                "id": entry_id,
                "catalogId": entry_id,
                "title": score["title"],
                "provenance": provenance,
                "hash": provenance["sourceSha256"],
                "resourceHash": digest(data),
                "options": {"tracks": [1], "speed": 1, "transpose": sid % 5 - 2},
                "fixtureOnly": True,
            }
            row = (
                entry_id,
                provenance["workId"],
                relative,
                digest(data),
                provenance["sourceSha256"],
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            )
            self.new_rows.append(row)
            self.new_metadata[entry_id] = metadata
            self.new_scores[entry_id] = data

        self.catalog(self.stage, self.old_rows + self.new_rows)
        for target in (self.runtime / "Songs", self.source):
            self.catalog(target, self.old_rows)
            for row in self.old_rows:
                shutil.copyfile(self.stage / row[2], target / row[2])
        if self.write_manifest:
            songs = []
            for row in self.new_rows:
                metadata = self.new_metadata[row[0]]
                provenance = metadata["provenance"]
                songs.append({
                    "id": row[2].removeprefix(self.batch_prefix + "-").removesuffix(".json"),
                    "title": metadata["title"],
                    "workId": provenance["workId"],
                    "editionId": provenance["editionId"],
                    "versionLabel": provenance["versionLabel"],
                    "sourceUrl": provenance["sourceUrl"],
                    "sourceSha256": provenance["sourceSha256"],
                })
            self.manifest_path.write_text(
                json.dumps({"provider": self.provider, "songs": songs}, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )

    def catalog(self, root, rows):
        catalog = root / "catalog.db"
        if catalog.exists():
            catalog.unlink()
        with contextlib.closing(sqlite3.connect(catalog)) as connection:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    INSERT INTO meta VALUES('schema','fixture-1'),('synthetic','0');
                    CREATE TABLE entries(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                        relative_path TEXT NOT NULL,content_hash TEXT NOT NULL,
                        original_hash TEXT NOT NULL,metadata_json TEXT NOT NULL);
                    CREATE TABLE search_index(entry_id TEXT PRIMARY KEY,title_key TEXT NOT NULL,
                        timing_verified INTEGER NOT NULL,human_reviewed INTEGER NOT NULL);
                    """
                )
                connection.executemany("INSERT INTO entries VALUES(?,?,?,?,?,?)", rows)
                connection.executemany(
                    "INSERT INTO search_index VALUES(?,?,?,?)",
                    [(row[0], title_key(json.loads(row[5])["title"]), 1, 0) for row in rows],
                )

    def sql(self, root, query, args=()):
        with contextlib.closing(sqlite3.connect(root / "catalog.db")) as connection:
            with connection:
                return connection.execute(query, args).fetchall()

    def metadata_for(self, sid):
        entry_id = f"builtin:{self._batch_relative(sid)}"
        return json.loads(self.sql(self.stage, "SELECT metadata_json FROM entries WHERE id=?", (entry_id,))[0][0])

    def rewrite_new(
        self,
        sid,
        *,
        title=None,
        work_id=None,
        edition_id=None,
        version_label=UNSET,
        artists=UNSET,
        update_catalog_work=True,
    ):
        relative = self._batch_relative(sid)
        entry_id = f"builtin:{relative}"
        score = json.loads((self.stage / relative).read_text(encoding="utf-8"))
        metadata = self.metadata_for(sid)
        provenance = dict(metadata["provenance"])
        if title is not None:
            score["title"] = title
            metadata["title"] = title
        if work_id is not None:
            provenance["workId"] = work_id
        if edition_id is not None:
            provenance["editionId"] = edition_id
        if version_label is not UNSET:
            provenance["versionLabel"] = version_label
        if artists is not UNSET:
            provenance["artists"] = artists
        score["provenance"] = provenance
        metadata["provenance"] = provenance
        data = json_bytes(score)
        (self.stage / relative).write_bytes(data)
        metadata["resourceHash"] = digest(data)
        catalog_work = provenance["workId"] if update_catalog_work else None
        if catalog_work is None:
            catalog_work = self.sql(self.stage, "SELECT work_id FROM entries WHERE id=?", (entry_id,))[0][0]
        self.sql(
            self.stage,
            "UPDATE entries SET work_id=?,content_hash=?,original_hash=?,metadata_json=? WHERE id=?",
            (
                catalog_work,
                digest(data),
                provenance["sourceSha256"],
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                entry_id,
            ),
        )
        self.sql(self.stage, "UPDATE search_index SET title_key=? WHERE entry_id=?", (title_key(metadata["title"]), entry_id))

    def set_metadata_field(self, sid, field, value):
        entry_id = f"builtin:{self._batch_relative(sid)}"
        metadata = self.metadata_for(sid)
        metadata[field] = value
        self.sql(
            self.stage,
            "UPDATE entries SET metadata_json=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), entry_id),
        )

    def baseline_title(self, index=1):
        return json.loads(self.old_rows[index - 1][5])["title"]

    def baseline_work_id(self, index=1):
        return self.old_rows[index - 1][1]

    def baseline_edition_id(self, index=1):
        return json.loads(self.old_rows[index - 1][5])["provenance"]["editionId"]


def file_states(fixture):
    return {
        "runtime": update.tree_state(fixture.runtime),
        "source": update.tree_state(fixture.source),
        "stage": update.tree_state(fixture.stage),
    }


class UpdatePopBatchAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = DisposableFixture(baseline_count=3, batch_count=4)
        self.addCleanup(self.fixture.close)

        self.workspace_patch = mock.patch.object(update, "WORKSPACE", self.fixture.workspace)
        self.workspace_patch.start()
        self.addCleanup(self.workspace_patch.stop)

        self.process_probe_patch = mock.patch.object(update, "active_instances", return_value=[])
        self.process_probe = self.process_probe_patch.start()
        self.addCleanup(self.process_probe_patch.stop)

    def run_update(self, apply=False, fixture=None, *, provider=None, source_root=None, language_policy="none"):
        fixture = fixture or self.fixture
        return update.deploy(
            fixture.stage,
            fixture.runtime,
            fixture.source,
            fixture.backup,
            fixture.report,
            apply,
            provider=provider,
            source_root=source_root,
            language_policy=language_policy,
        )

    def assert_preflight_refuses(self, exception=ValueError, fixture=None):
        fixture = fixture or self.fixture
        before = file_states(fixture)
        with self.assertRaises(exception):
            self.run_update(True, fixture=fixture)
        self.assertEqual(before, file_states(fixture))
        self.assertFalse(fixture.backup.exists())
        self.assertFalse(fixture.report.exists())

    def test_chinese_language_policy_rejects_unmarked_and_mixed_batches(self):
        chinese_tags = ["\u4e2d\u6587\u6b4c\u66f2", "\u4e2d\u6587\u6d41\u884c\u5019\u9009"]
        accepted = {"languageTags": ["zh"], "tags": chinese_tags}
        update._enforce_language_policy(accepted, "zh-001.json", "chinese-pop-first")
        with self.assertRaisesRegex(ValueError, "explicit languageTags"):
            update._enforce_language_policy({"tags": chinese_tags}, "missing-language.json", "chinese-pop-first")
        with self.assertRaisesRegex(ValueError, "only zh/cmn/yue"):
            update._enforce_language_policy({"languageTags": ["zh", "en"], "tags": chinese_tags}, "mixed.json", "chinese-pop-first")
        with self.assertRaisesRegex(ValueError, "explicit priority tag"):
            update._enforce_language_policy(accepted, "main-without-priority.json", "chinese-pop-main")
        update._enforce_language_policy({"languageTags": ["cmn"], "tags": chinese_tags + ["\u5927\u4f17\u4f18\u5148"]}, "main-accepted.json", "chinese-pop-main")

    def test_chinese_language_policy_blocks_a_realistic_unmarked_fixture_before_writes(self):
        before = file_states(self.fixture)
        with self.assertRaisesRegex(ValueError, "explicit languageTags"):
            self.run_update(True, language_policy="chinese-pop-first")
        self.assertEqual(before, file_states(self.fixture))
        self.assertFalse(self.fixture.backup.exists())
        self.assertFalse(self.fixture.report.exists())

    def test_provider_prefix_separator_variant_is_not_duplicated(self):
        self.assertEqual(
            update._manifest_relative(
                {"id": "openscore-lieder-28789279"},
                "OpenScoreLieder",
                "fixture.json",
            ),
            "openscore-lieder-28789279.json",
        )
        self.assertEqual(
            update._manifest_relative({"id": "pdmx-a1b2c3-001"}, "PDMX", "fixture.json"),
            "pdmx-a1b2c3-001.json",
        )
        self.assertEqual(
            update._manifest_relative({"id": "pdmxfoo-001"}, "PDMX", "fixture.json"),
            "pdmx-pdmxfoo-001.json",
        )

    def test_dynamic_601_increment_is_not_hardcoded_and_applies_exact_delta(self):
        fixture = DisposableFixture(baseline_count=3, batch_count=601)
        self.addCleanup(fixture.close)
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            result = self.run_update(True, fixture=fixture)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["newBuiltinCount"], 601)
        self.assertEqual(result["addedScoresPerTarget"], 601)
        self.assertEqual(len(result["addedFiles"]), 1202)
        self.assertEqual(len(update.read_catalog(fixture.runtime / "Songs").entries), 604)
        self.assertEqual(len(update.read_catalog(fixture.source).entries), 604)
        self.assertEqual(update.read_catalog(fixture.runtime / "Songs"), update.read_catalog(fixture.stage))
        self.assertEqual(update.read_catalog(fixture.source), update.read_catalog(fixture.stage))
        self.assertTrue((fixture.backup / "before.json").is_file())
        self.assertTrue((fixture.backup / "runtime-catalog.db").is_file())
        self.assertTrue((fixture.backup / "source-catalog.db").is_file())
        self.assertEqual((fixture.runtime / "QinBan.exe").read_bytes(), b"FAKE FIXTURE EXE; NEVER EXECUTED")
        self.assertEqual((fixture.runtime / "UserData" / "preferences.json").read_bytes(), b"private fixture preferences")

    def test_pdmx_manifest_derived_ids_are_accepted_in_preflight_only(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        before = file_states(fixture)
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            result = self.run_update(False, fixture=fixture)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["provider"], "PDMX")
        self.assertEqual(result["newBuiltinCount"], fixture.batch_count)
        self.assertEqual(result["stageManifestPaths"], [str(fixture.manifest_path)])
        self.assertEqual(before, file_states(fixture))
        self.assertFalse(fixture.backup.exists())
        self.assertTrue(fixture.report.is_file())

    def test_pascalcase_manifest_fields_are_accepted_for_stage_and_source(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        lower_stage = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        fixture.manifest_path.write_text(
            json.dumps(pascal_manifest(lower_stage), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

        source_root = fixture.workspace / "source-intake-pascal"
        source_root.mkdir()
        source_songs = []
        midi_paths = []
        for row in fixture.new_rows:
            metadata = fixture.new_metadata[row[0]]
            provenance = metadata["provenance"]
            filename = row[2].replace(".json", ".mid")
            source_file = source_root / "midi" / filename
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_bytes(
                f"fake {fixture.provider} source bytes {filename[5:8]}".encode("ascii")
            )
            reference_file = source_root / "references" / (filename.removesuffix(".mid") + ".json")
            reference_file.parent.mkdir(parents=True, exist_ok=True)
            reference_file.write_text("{}", encoding="utf-8")
            midi_path = str(Path("midi") / filename)
            midi_paths.append(midi_path)
            source_songs.append({
                "id": filename.removeprefix("pdmx-").removesuffix(".mid"),
                "title": metadata["title"],
                "workId": provenance["workId"],
                "editionId": provenance["editionId"],
                "versionLabel": provenance["versionLabel"],
                "sourceUrl": provenance["sourceUrl"],
                "sourceSha256": provenance["sourceSha256"],
            })
        (source_root / "manifest.json").write_text(
            json.dumps(
                pascal_manifest({"provider": "PDMX", "songs": source_songs}, midi_paths=midi_paths),
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        before = file_states(fixture)
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            result = self.run_update(
                False, fixture=fixture, provider="PDMX", source_root=source_root
            )
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["provider"], "PDMX")
        self.assertEqual(result["sourceRoot"], str(source_root))
        self.assertEqual(before, file_states(fixture))
        self.assertFalse(fixture.backup.exists())

    def test_conflicting_pascal_and_lower_manifest_aliases_are_refused(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["Provider"] = "OtherProvider"
        fixture.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            with self.assertRaisesRegex(ValueError, "Conflicting manifest aliases"):
                self.run_update(False, fixture=fixture)
        self.assertFalse(fixture.report.exists())
        self.assertFalse(fixture.backup.exists())

    def test_title_placeholder_is_not_a_legal_builtin_id(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["songs"][0]["id"] = manifest["songs"][0]["title"]
        fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            with self.assertRaisesRegex(ValueError, "provider/stable-id"):
                self.run_update(False, fixture=fixture)
        self.assertFalse(fixture.report.exists())

    def test_manifest_provider_mismatch_is_refused_before_report(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["provider"] = "OtherProvider"
        fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            with self.assertRaisesRegex(ValueError, "(Stage manifest is missing new score|Provenance differs from stage/source manifest)"):
                self.run_update(False, fixture=fixture)
        self.assertFalse(fixture.report.exists())
        self.assertFalse(fixture.backup.exists())

    def test_manifest_source_hash_mismatch_is_refused_before_report(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["songs"][0]["sourceSha256"] = "F" * 64
        fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            with self.assertRaisesRegex(ValueError, "Provenance differs from stage/source manifest"):
                self.run_update(False, fixture=fixture)
        self.assertFalse(fixture.report.exists())
        self.assertFalse(fixture.backup.exists())

    def test_source_root_manifest_and_source_hash_are_checked(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        source_root = fixture.workspace / "source-intake"
        source_root.mkdir()
        source_songs = []
        for row in fixture.new_rows:
            metadata = fixture.new_metadata[row[0]]
            provenance = metadata["provenance"]
            filename = row[2].replace(".json", ".mid")
            source_file = source_root / "midi" / filename
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_bytes(f"fake {fixture.provider} source bytes {filename[5:8]}".encode("ascii"))
            self.assertEqual(update.sha(source_file), provenance["sourceSha256"])
            source_songs.append({
                "id": filename.removeprefix("pdmx-").removesuffix(".mid"),
                "title": metadata["title"],
                "workId": provenance["workId"],
                "editionId": provenance["editionId"],
                "versionLabel": provenance["versionLabel"],
                "sourceUrl": provenance["sourceUrl"],
                "sourceSha256": provenance["sourceSha256"],
                "midiPath": str(Path("midi") / filename),
            })
        (source_root / "manifest.json").write_text(
            json.dumps({"provider": "PDMX", "songs": source_songs}, ensure_ascii=False),
            encoding="utf-8",
        )
        before = file_states(fixture)
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            result = self.run_update(False, fixture=fixture, provider="PDMX", source_root=source_root)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["provider"], "PDMX")
        self.assertEqual(result["sourceRoot"], str(source_root))
        self.assertEqual(before, file_states(fixture))
        self.assertFalse(fixture.backup.exists())

    def test_provider_override_mismatch_is_refused(self):
        fixture = DisposableFixture(provider="PDMX", batch_prefix="pdmx", write_manifest=True)
        self.addCleanup(fixture.close)
        with mock.patch.object(update, "WORKSPACE", fixture.workspace):
            with self.assertRaisesRegex(ValueError, "--provider disagrees"):
                self.run_update(False, fixture=fixture, provider="POP909")
        self.assertFalse(fixture.report.exists())

    def test_duplicate_edition_id_is_refused_against_existing_baseline(self):
        self.fixture.rewrite_new(1, edition_id=self.fixture.baseline_edition_id())
        with self.assertRaisesRegex(ValueError, "Duplicate editionId"):
            self.run_update(True)
        self.assertFalse(self.fixture.backup.exists())
        self.assertFalse(self.fixture.report.exists())

    def test_catalog_work_id_must_match_normalized_provenance(self):
        self.fixture.rewrite_new(1, work_id="mismatched-work", update_catalog_work=False)
        self.assert_preflight_refuses(ValueError)

    def test_empty_work_id_is_refused(self):
        self.fixture.rewrite_new(1, work_id="")
        self.assert_preflight_refuses(ValueError)

    def test_empty_edition_id_is_refused(self):
        self.fixture.rewrite_new(1, edition_id="")
        self.assert_preflight_refuses(ValueError)

    def test_exact_old_title_collision_rejects_same_work_without_version_label(self):
        self.fixture.rewrite_new(
            1,
            title=self.fixture.baseline_title(),
            work_id=self.fixture.baseline_work_id(),
            version_label="",
        )
        with self.assertRaisesRegex(ValueError, "Exact title collision"):
            self.run_update(True)
        self.assertFalse(self.fixture.report.exists())

    def test_exact_old_title_collision_allows_different_work_without_version_label(self):
        self.fixture.rewrite_new(
            1,
            title=self.fixture.baseline_title(),
            work_id="different-work",
            version_label="",
        )
        result = self.run_update(False)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["newBuiltinCount"], 4)

    def test_exact_old_title_collision_allows_different_work_with_version_label(self):
        self.fixture.rewrite_new(
            1,
            title=self.fixture.baseline_title(),
            work_id="different-work",
            version_label="live",
        )
        result = self.run_update(False)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["newBuiltinCount"], 4)

    def test_same_work_id_cannot_bypass_collision_with_artist_alias_change(self):
        self.fixture.rewrite_new(
            1,
            title=self.fixture.baseline_title(),
            work_id=self.fixture.baseline_work_id(),
            artists=["Fixture Artist", "Alias Artist"],
            version_label="",
        )
        with self.assertRaisesRegex(ValueError, "Exact title collision"):
            self.run_update(True)
        self.assertFalse(self.fixture.report.exists())

    def test_exact_old_title_collision_allows_labelled_same_work(self):
        self.fixture.rewrite_new(
            1,
            title=self.fixture.baseline_title(),
            work_id=self.fixture.baseline_work_id(),
            edition_id="labelled-edition-001",
            version_label="live",
        )
        result = self.run_update(False)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["newBuiltinCount"], 4)
        self.assertTrue(self.fixture.report.is_file())
        self.assertFalse(self.fixture.backup.exists())

    def test_exact_new_title_collision_requires_two_nonempty_labels_of_one_work(self):
        self.fixture.rewrite_new(1, title="Same new fixture title", work_id="shared-work", artists=["Shared Artist"], version_label="piano")
        self.fixture.rewrite_new(2, title="Same new fixture title", work_id="shared-work", artists=["Shared Artist"], version_label="")
        with self.assertRaisesRegex(ValueError, "Exact new title collision"):
            self.run_update(True)
        self.assertFalse(self.fixture.report.exists())

    def test_exact_new_title_collision_allows_distinct_labelled_editions_of_one_work(self):
        self.fixture.rewrite_new(
            1,
            title="Same new fixture title",
            work_id="shared-work",
            edition_id="shared-edition-001",
            artists=["Shared Artist"],
            version_label="piano",
        )
        self.fixture.rewrite_new(
            2,
            title="Same new fixture title",
            work_id="shared-work",
            edition_id="shared-edition-002",
            artists=["Shared Artist"],
            version_label="live",
        )
        result = self.run_update(False)
        self.assertEqual(result["status"], "DRY-RUN-PASS")
        self.assertEqual(result["newBuiltinCount"], 4)

    def test_runtime_source_baseline_count_mismatch_is_refused(self):
        self.fixture.catalog(self.fixture.source, self.fixture.old_rows[:-1])
        self.assert_preflight_refuses(ValueError)

    def test_stage_must_strictly_add_over_baseline(self):
        self.fixture.catalog(self.fixture.stage, self.fixture.old_rows)
        self.assert_preflight_refuses(ValueError)

    def test_source_hash_metadata_error_is_refused_before_any_write(self):
        self.fixture.set_metadata_field(1, "hash", "F" * 64)
        self.assert_preflight_refuses(ValueError)

    def test_resource_hash_metadata_error_is_refused_before_any_write(self):
        self.fixture.set_metadata_field(1, "resourceHash", "E" * 64)
        self.assert_preflight_refuses(ValueError)

    def test_catalog_race_is_detected_after_read(self):
        catalog = (self.fixture.stage / "catalog.db").resolve()
        original_sha = update.sha
        catalog_calls = 0

        def racing_sha(path):
            nonlocal catalog_calls
            value = original_sha(path)
            if Path(path).resolve() == catalog:
                catalog_calls += 1
                if catalog_calls == 2:
                    return "0" * 64 if value != "0" * 64 else "1" * 64
            return value

        with mock.patch.object(update, "sha", side_effect=racing_sha):
            with self.assertRaisesRegex(ValueError, "Catalogue raced during read"):
                update.read_catalog(self.fixture.stage)
        self.assertEqual(catalog_calls, 2)

    def test_qinban_process_probe_failure_fails_closed_without_report_or_backup(self):
        self.process_probe.side_effect = subprocess.TimeoutExpired("fixture QinBan probe", 30)
        before = file_states(self.fixture)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_update(True)
        self.assertEqual(before, file_states(self.fixture))
        self.assertFalse(self.fixture.backup.exists())
        self.assertFalse(self.fixture.report.exists())

    def test_existing_backup_is_never_overwritten(self):
        self.fixture.backup.mkdir(parents=True)
        sentinel = self.fixture.backup / "sentinel.txt"
        sentinel.write_bytes(b"do not overwrite")
        before = file_states(self.fixture)
        with self.assertRaises(FileExistsError):
            self.run_update(True)
        self.assertEqual(before, file_states(self.fixture))
        self.assertEqual(sentinel.read_bytes(), b"do not overwrite")
        self.assertFalse(self.fixture.report.exists())

    def test_existing_report_is_never_overwritten(self):
        self.fixture.report.write_bytes(b"do not overwrite report")
        before = file_states(self.fixture)
        with self.assertRaises(FileExistsError):
            self.run_update(True)
        self.assertEqual(before, file_states(self.fixture))
        self.assertEqual(self.fixture.report.read_bytes(), b"do not overwrite report")
        self.assertFalse(self.fixture.backup.exists())

    def test_rollback_refuses_to_overwrite_a_later_user_catalogue(self):
        original_atomic_copy = update.atomic_copy
        user_catalogue = b"later user catalogue bytes; never overwrite"

        def switching(src, dst, **kwargs):
            if Path(dst) == self.fixture.source / "catalog.db" and Path(src) == self.fixture.stage / "catalog.db":
                (self.fixture.runtime / "Songs" / "catalog.db").write_bytes(user_catalogue)
                raise OSError("injected second switch failure")
            return original_atomic_copy(src, dst, **kwargs)

        before_runtime = update.sha(self.fixture.runtime / "Songs" / "catalog.db")
        before_source = update.sha(self.fixture.source / "catalog.db")
        with mock.patch.object(update, "atomic_copy", side_effect=switching):
            with self.assertRaisesRegex(OSError, "injected second switch failure"):
                self.run_update(True)

        result = json.loads(self.fixture.report.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual((self.fixture.runtime / "Songs" / "catalog.db").read_bytes(), user_catalogue)
        self.assertEqual(update.sha(self.fixture.source / "catalog.db"), before_source)
        self.assertNotEqual(update.sha(self.fixture.runtime / "Songs" / "catalog.db"), before_runtime)
        self.assertTrue(result["manualRecoveryRequired"])
        self.assertTrue(any(not item["restored"] for item in result["rollback"]))
        self.assertEqual(len(result["copiedNewFilesPreserved"]), self.fixture.batch_count * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)


