"""Disposable POP200 fixtures only; never real Songs/UserData/MIDI/deployment.
Dummy provenance imitates the intake contract, not actual source-song evidence.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import update_pop200_library as update


def digest(data):
    return hashlib.sha256(data).hexdigest().upper()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qinban-pop200-fixture-')
        self.workspace = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.runtime = self.workspace / 'dist/existing'
        self.source = self.workspace / 'repo/Songs'
        self.stage = self.workspace / 'stage/Songs'
        self.backup = self.workspace / 'evidence/backup'
        self.report = self.workspace / 'evidence/report.json'
        for path in (self.runtime / 'Songs', self.source, self.stage):
            path.mkdir(parents=True)
        resources = {'QinBan.exe': b'FAKE FIXTURE EXE, NEVER EXECUTED',
                     'UserData/library.db': b'NOT SQLITE; HASH ONLY',
                     'UserData/preferences.json': b'fixture user preferences',
                     'UserData/backgrounds/private.bin': b'fixture private bytes',
                     'licenses/POP909-repository-MIT.txt': b'fixture license; keep exact',
                     'QINBAN-NOTICES.md': b'fixture notices; keep exact'}
        for rel, data in resources.items():
            path = self.runtime / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.runtime / 'UserData/empty').mkdir()
        (self.source / 'private-extra.txt').write_bytes(b'uncatalogued user data')
        (self.source / 'nested').mkdir()
        (self.source / 'nested/keep.txt').write_bytes(b'protect whole source tree')
        self.old_rows, self.new_rows = [], []
        for i in range(32):
            rel = f'old{i:02}.json'
            score = {'title': f'old title {i:02}', 'notes': [], 'fixtureOnly': True}
            data = json.dumps(score).encode()
            (self.stage / rel).write_bytes(data)
            metadata = {'title': score['title'], 'options': {'transpose': i % 3, 'speed': 1},
                        'provenance': {'provider': 'fixture', 'synthetic': True},
                        'opaquePublishedField': 'must remain byte-exact'}
            self.old_rows.append((f'builtin:{rel}', f'fixture:{i}', rel, digest(data), digest(data), json.dumps(metadata)))
        for sid in range(1, 301):
            rel = f'pop909-{sid:03}.json'
            id_ = 'builtin:' + rel
            source_hash = digest(f'FAKE MIDI SOURCE FIXTURE {sid}'.encode())
            prov = {'provider': 'POP909', 'workId': f'pop909:{sid:03}', 'artists': ['fixture artist'],
                    'sourceUrl': f'{update.POP_URL}/POP909/{sid:03}/{sid:03}.mid',
                    'sourceSha256': source_hash, 'synthetic': False, 'redistributionVerified': False,
                    'musicReview': 'not-reviewed', 'gameReview': 'not-tested', 'timingStatus': 'source-compared'}
            score = {'title': f'fixture pop title {sid:03}', 'provenance': prov, 'fixtureOnly': True,
                     'notes': [{'pitch': 60, 'startMs': 0, 'durationMs': 500}]}
            data = json.dumps(score).encode()
            (self.stage / rel).write_bytes(data)
            metadata = {'id': id_, 'catalogId': id_, 'title': score['title'], 'provenance': prov,
                        'hash': source_hash, 'resourceHash': digest(data),
                        'options': {'tracks': [1], 'speed': 1, 'transpose': sid % 5 - 2}}
            row = (id_, prov['workId'], rel, digest(data), source_hash, json.dumps(metadata))
            (self.old_rows if sid <= 100 else self.new_rows).append(row)
        self.catalog(self.stage, self.old_rows + self.new_rows)
        for target in (self.runtime / 'Songs', self.source):
            self.catalog(target, self.old_rows)
            for row in self.old_rows:
                shutil.copyfile(self.stage / row[2], target / row[2])
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(update, 'WORKSPACE', self.workspace).start()
        self.process_probe = mock.patch.object(update, 'active_instances', return_value=[]).start()

    def cleanup(self):
        # Only this verified disposable fixture; no product/workspace cleanup.
        root = Path(self.temp.name).resolve()
        if root != self.workspace or not root.name.startswith('qinban-pop200-fixture-'):
            raise AssertionError('Unexpected cleanup target')
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def catalog(self, root, rows):
        with contextlib.closing(sqlite3.connect(root / 'catalog.db')) as db:
            with db:
                db.executescript('''
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    INSERT INTO meta VALUES('schema','1'),('synthetic','0');
                    CREATE TABLE entries(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                        relative_path TEXT NOT NULL,content_hash TEXT NOT NULL,
                        original_hash TEXT NOT NULL,metadata_json TEXT NOT NULL);
                    CREATE TABLE search_index(entry_id TEXT PRIMARY KEY,title_key TEXT NOT NULL,
                        timing_verified INTEGER NOT NULL,human_reviewed INTEGER NOT NULL);
                ''')
                db.executemany('INSERT INTO entries VALUES(?,?,?,?,?,?)', rows)
                db.executemany('INSERT INTO search_index VALUES(?,?,?,?)',
                               [(row[0], json.loads(row[5])['title'], 1, 0) for row in rows])

    def sql(self, root, query, args=()):
        with contextlib.closing(sqlite3.connect(root / 'catalog.db')) as db:
            with db:
                return db.execute(query, args).fetchall()

    def run_update(self, apply=False, **paths):
        return update.deploy(paths.get('staged', self.stage), paths.get('runtime', self.runtime),
                             paths.get('source', self.source), paths.get('backup', self.backup),
                             paths.get('report', self.report), apply)

    def result(self):
        return json.loads(self.report.read_text(encoding='utf-8'))

    def before(self):
        return {'runtime': update.tree_state(self.runtime), 'source': update.tree_state(self.source),
                'stage': update.tree_state(self.stage)}

    def assert_preflight_refuses(self, exception=ValueError, **paths):
        before = self.before()
        with self.assertRaises(exception):
            self.run_update(True, **paths)
        self.assertEqual(before, self.before())
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.report.exists())

    def new_metadata(self, sid=101):
        return json.loads(self.sql(self.stage, 'SELECT metadata_json FROM entries WHERE id=?',
                                   (f'builtin:pop909-{sid:03}.json',))[0][0])

    def change_new(self, change, sid=101, change_score=True):
        rel = f'pop909-{sid:03}.json'
        metadata = self.new_metadata(sid)
        change(metadata)
        if change_score:
            score = json.loads((self.stage / rel).read_text(encoding='utf-8'))
            score['title'], score['provenance'] = metadata.get('title'), metadata.get('provenance')
            data = json.dumps(score).encode()
            (self.stage / rel).write_bytes(data)
            metadata['resourceHash'] = digest(data)
        self.sql(self.stage, 'UPDATE entries SET metadata_json=?,content_hash=? WHERE id=?',
                 (json.dumps(metadata), metadata['resourceHash'], 'builtin:' + rel))

    def restore_new(self, row, score):
        (self.stage / row[2]).write_bytes(score)
        self.sql(self.stage, 'UPDATE entries SET content_hash=?,metadata_json=? WHERE id=?', (row[3], row[5], row[0]))

    def assert_old_catalogs(self, before):
        self.assertEqual(update.sha(self.runtime / 'Songs/catalog.db'), before['runtime']['files']['Songs/catalog.db'])
        self.assertEqual(update.sha(self.source / 'catalog.db'), before['source']['files']['catalog.db'])

    def test_dry_run_full_snapshots_manifest332_and_no_target_writes(self):
        before = self.before()
        result = self.run_update()
        self.assertEqual(result['status'], 'DRY-RUN-PASS')
        self.assertEqual(before, self.before())
        self.assertFalse(self.backup.exists())
        self.assertEqual((result['manifest']['entries'], len(result['manifest']['scores']),
                          result['manifest']['newEntries'], result['newBuiltinCount']), (332, 332, 200, 332))
        self.assertEqual(result['runtimeSnapshot'], before['runtime']['files'])
        self.assertEqual(result['sourceSnapshot'], before['source']['files'])
        for operation in result['operations']:
            self.assertEqual((operation['oldEntries'], operation['newEntries'], len(operation['addFiles'])), (132, 332, 200))
        self.assertEqual(self.result(), result)

    def test_apply_exact_delta_both_targets_and_latest_backups(self):
        (self.runtime / 'UserData/preferences.json').write_bytes(b'latest user edit before preflight')
        before = self.before()
        incoming = update.read_catalog(self.stage)
        originals = [update.read_catalog(self.runtime / 'Songs'), update.read_catalog(self.source)]
        result = self.run_update(True)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(result['addedFiles']), 400)
        self.assertEqual(update.tree_state(self.stage), before['stage'])
        for label, original in zip(('runtime', 'source'), originals):
            target = self.runtime / 'Songs' if label == 'runtime' else self.source
            actual = update.read_catalog(target)
            self.assertEqual(actual, incoming)
            for id_, row in original.rows.items():
                self.assertEqual(actual.rows[id_], row)
            rel = 'Songs/catalog.db' if label == 'runtime' else 'catalog.db'
            after = update.tree_state(self.runtime if label == 'runtime' else self.source)
            self.assertEqual(len(set(after['files']) - set(before[label]['files'])), 200)
            for old_rel, old_hash in before[label]['files'].items():
                if old_rel != rel:
                    self.assertEqual(after['files'][old_rel], old_hash)
                    self.assertEqual(after['fileModes'][old_rel], before[label]['fileModes'][old_rel])
            self.assertEqual(before[label]['directories'], after['directories'])
            self.assertEqual(update.sha(self.backup / (label + '-catalog.db')), before[label]['files'][rel])
        saved = json.loads((self.backup / 'before.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['states'], {label: before[label] for label in ('runtime', 'source')})
        self.assertEqual(saved['manifest']['entries'], 332)
        for key in ('exactAllowedDeltaVerifiedForRuntimeAndSource', 'exeUnchanged', 'userDataUnchanged'):
            self.assertTrue(result[key])
        for key in ('actualUserDataDatabasesOpened', 'newDistributionFolderCreated', 'automaticResumeSupported'):
            self.assertFalse(result[key])
        self.assertEqual(self.result(), result)

    def test_manifest_comes_from_stage_not_legacy_tool_manifest(self):
        stale = b'{"count":132,"scores":[]}'
        (self.source / 'builtin-manifest.json').write_bytes(stale)
        (self.stage / 'builtin-manifest.json').write_bytes(stale)
        result = self.run_update(True)
        self.assertEqual(len(result['manifest']['scores']), 332)
        self.assertEqual((self.source / 'builtin-manifest.json').read_bytes(), stale)
        self.assertFalse((self.runtime / 'Songs/builtin-manifest.json').exists())

    def test_sqlite_is_readonly_catalog_only_and_no_sidecar_created(self):
        original, calls = sqlite3.connect, []
        def connect(database, *args, **kwargs):
            calls.append((database, kwargs))
            return original(database, *args, **kwargs)
        with mock.patch.object(update.sqlite3, 'connect', side_effect=connect):
            self.run_update(True)
        self.assertTrue(calls)
        for database, kwargs in calls:
            self.assertIn('catalog.db?mode=ro&immutable=1', database)
            self.assertNotIn('UserData', database)
            self.assertTrue(kwargs['uri'])
        for target in (self.stage, self.source, self.runtime / 'Songs'):
            for suffix in ('-wal', '-shm', '-journal'):
                self.assertFalse((target / ('catalog.db' + suffix)).exists())

    def test_old_files_are_never_opened_for_copy_to_targets(self):
        original, destinations = update._copy_exclusive, []
        def copying(src, dst, *args, **kwargs):
            destinations.append(dst)
            return original(src, dst, *args, **kwargs)
        with mock.patch.object(update, '_copy_exclusive', side_effect=copying):
            self.run_update(True)
        scores = [path for path in destinations if path.parent in (self.source, self.runtime / 'Songs')]
        self.assertEqual(len(scores), 400)
        self.assertEqual({path.name for path in scores}, {row[2] for row in self.new_rows})

    def test_readonly_catalogues_keep_modes_on_success(self):
        for target in (self.runtime / 'Songs/catalog.db', self.source / 'catalog.db'):
            os.chmod(target, stat.S_IREAD)
        self.assertTrue(self.run_update(True)['runtimeCatalogReadOnly'])
        for target in (self.runtime / 'Songs/catalog.db', self.source / 'catalog.db'):
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE)

    def test_fixed_stage_count_refuses331_and333(self):
        row = self.new_rows[-1]
        self.sql(self.stage, 'DELETE FROM search_index WHERE entry_id=?', (row[0],))
        self.sql(self.stage, 'DELETE FROM entries WHERE id=?', (row[0],))
        self.assert_preflight_refuses()
        self.sql(self.stage, 'INSERT INTO entries VALUES(?,?,?,?,?,?)', row)
        self.sql(self.stage, 'INSERT INTO search_index VALUES(?,?,?,?)', (row[0], json.loads(row[5])['title'], 1, 0))
        extra = list(row)
        extra[0], extra[2] = 'builtin:extra.json', 'extra.json'
        shutil.copyfile(self.stage / row[2], self.stage / extra[2])
        self.sql(self.stage, 'INSERT INTO entries VALUES(?,?,?,?,?,?)', extra)
        self.sql(self.stage, 'INSERT INTO search_index VALUES(?,?,?,?)', (extra[0], 'extra', 1, 0))
        self.assert_preflight_refuses()

    def test_both_baselines_must_be_exactly132(self):
        for target in (self.runtime / 'Songs', self.source):
            row = self.old_rows[-1]
            with self.subTest(target=target):
                self.sql(target, 'DELETE FROM search_index WHERE entry_id=?', (row[0],))
                self.sql(target, 'DELETE FROM entries WHERE id=?', (row[0],))
                self.assert_preflight_refuses()
                self.sql(target, 'INSERT INTO entries VALUES(?,?,?,?,?,?)', row)
                self.sql(target, 'INSERT INTO search_index VALUES(?,?,?,?)', (row[0], json.loads(row[5])['title'], 1, 0))

    def test_old_metadata_defaults_original_hash_and_id_are_byte_exact(self):
        row = self.old_rows[0]
        mutations = [('metadata_json', json.dumps(json.loads(row[5]), indent=2)),
                     ('metadata_json', json.dumps({'title': 'changed', 'options': {'transpose': 7}})),
                     ('original_hash', 'A' * 64), ('work_id', 'changed'), ('id', 'builtin:changed-id')]
        columns = ('id', 'work_id', 'relative_path', 'content_hash', 'original_hash', 'metadata_json')
        for column, value in mutations:
            with self.subTest(column=column):
                self.sql(self.stage, 'UPDATE entries SET ' + column + '=? WHERE id=?', (value, row[0]))
                self.assert_preflight_refuses()
                if column == 'id':
                    self.sql(self.stage, 'UPDATE entries SET id=? WHERE id=?', (row[0], value))
                else:
                    self.sql(self.stage, 'UPDATE entries SET ' + column + '=? WHERE id=?', (row[columns.index(column)], row[0]))

    def test_runtime_source_metadata_difference_refused(self):
        self.sql(self.source, 'UPDATE entries SET metadata_json=? WHERE id=?',
                 (json.dumps({'title': 'different source', 'options': {'transpose': 2}}), self.old_rows[0][0]))
        self.assert_preflight_refuses()

    def test_preserved_search_rows_and_classification_refused_if_changed(self):
        self.sql(self.stage, 'UPDATE search_index SET human_reviewed=1 WHERE entry_id=?', (self.old_rows[0][0],))
        self.assert_preflight_refuses()
        self.sql(self.stage, 'UPDATE search_index SET human_reviewed=0 WHERE entry_id=?', (self.old_rows[0][0],))
        self.sql(self.stage, "UPDATE meta SET value='1' WHERE key='synthetic'")
        self.assert_preflight_refuses()

    def test_existing_bytes_and_stage_resource_checksums_refused(self):
        for target in (self.runtime / 'Songs', self.source, self.stage):
            path = target / self.old_rows[0][2]
            original = path.read_bytes()
            with self.subTest(target=target):
                path.write_bytes(b'changed user score or corrupt stage')
                self.assert_preflight_refuses()
                path.write_bytes(original)

    def test_new_metadata_strict_flags_artists_and_timing_required(self):
        row = self.new_rows[0]
        score = (self.stage / row[2]).read_bytes()
        mutations = [('artists', []), ('artists', [' ']), ('artists', 'not a list'),
                     ('artists', ['fixture', ' FIXTURE ']), ('artists', [None]),
                     ('synthetic', True), ('synthetic', 0), ('synthetic', None),
                     ('redistributionVerified', True), ('redistributionVerified', 0),
                     ('musicReview', 'human-reviewed'), ('gameReview', 'verified-arrangement'),
                     ('timingStatus', 'unverified'), ('provider', 'fixture'), ('sourceSha256', 'not a hash'),
                     ('sourceUrl', 'https://untrusted.example/song.mid')]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                self.change_new(lambda m: m['provenance'].__setitem__(key, value))
                self.assert_preflight_refuses()
                self.restore_new(row, score)
        self.change_new(lambda m: m['provenance'].pop('synthetic'))
        self.assert_preflight_refuses()

    def test_new_metadata_matches_normalized_source_provenance(self):
        self.change_new(lambda m: m['provenance'].__setitem__('artists', ['different artist']), change_score=False)
        self.assert_preflight_refuses()

    def test_new_catalogue_source_hash_resource_hash_and_identity_checked(self):
        row = self.new_rows[0]
        score = (self.stage / row[2]).read_bytes()
        for key, value in [('hash', 'B' * 64), ('resourceHash', 'C' * 64), ('id', 'wrong'),
                           ('catalogId', 'wrong'), ('options', None)]:
            with self.subTest(key=key):
                self.change_new(lambda m: m.__setitem__(key, value), change_score=False)
                self.assert_preflight_refuses()
                self.restore_new(row, score)
        self.sql(self.stage, 'UPDATE entries SET original_hash=? WHERE id=?', ('D' * 64, row[0]))
        self.assert_preflight_refuses()

    def test_new_title_collisions_with_old_new_and_normalized_forms_refused(self):
        row = self.new_rows[0]
        score = (self.stage / row[2]).read_bytes()
        for title in ['old title 00', '  OLD   TITLE 00  ', 'fixture pop title 102', 'ＦＩＸＴＵＲＥ POP TITLE 102']:
            with self.subTest(title=title):
                self.change_new(lambda m: m.__setitem__('title', title))
                self.assert_preflight_refuses()
                self.restore_new(row, score)

    def test_new_nonpop_id_refused(self):
        row = self.new_rows[0]
        self.sql(self.stage, 'UPDATE entries SET id=? WHERE id=?', ('builtin:not-pop909', row[0]))
        self.sql(self.stage, 'UPDATE search_index SET entry_id=? WHERE entry_id=?', ('builtin:not-pop909', row[0]))
        self.assert_preflight_refuses()

    def test_new_path_collision_even_same_hash_refuses_without_resume(self):
        for target in (self.runtime / 'Songs', self.source):
            path = target / self.new_rows[0][2]
            for data in (b'user content at new path', (self.stage / path.name).read_bytes()):
                with self.subTest(target=target):
                    path.write_bytes(data)
                    self.assert_preflight_refuses(FileExistsError)
                    self.assertEqual(path.read_bytes(), data)
            path.unlink()  # Own disposable fixture only.

    def test_sqlite_sidecars_refused_in_all_three_libraries(self):
        for target in (self.stage, self.runtime / 'Songs', self.source):
            for suffix in ('-wal', '-shm', '-journal'):
                path = target / ('catalog.db' + suffix)
                with self.subTest(target=target, suffix=suffix):
                    path.write_bytes(b'fixture sidecar')
                    self.assert_preflight_refuses()
                    path.unlink()

    def test_corrupt_stage_catalogue_and_duplicate_json_keys_refused(self):
        path = self.stage / 'catalog.db'
        original = path.read_bytes()
        path.write_bytes(b'not sqlite')
        self.assert_preflight_refuses(sqlite3.DatabaseError)
        path.write_bytes(original)
        self.sql(self.stage, 'UPDATE entries SET metadata_json=? WHERE id=?',
                 ('{"title":"first","title":"second"}', self.new_rows[0][0]))
        self.assert_preflight_refuses()

    def test_overlapping_or_outside_workspace_paths_refused(self):
        cases = [{'staged': self.runtime / 'Songs'}, {'staged': self.source.parent},
                 {'source': self.runtime / 'Songs'}, {'backup': self.source / 'backup'},
                 {'backup': self.runtime / 'backup'}, {'report': self.stage / 'report.json'},
                 {'report': self.backup / 'report.json'}, {'backup': self.report},
                 {'backup': self.workspace.parent / 'outside-pop200-backup'},
                 {'source': self.workspace.parent / 'outside/Songs'}, {'staged': self.workspace},
                 {'staged': self.stage.parent / '../Songs'}]
        for paths in cases:
            with self.subTest(paths=paths):
                self.assert_preflight_refuses(**paths)

    def test_existing_backup_even_empty_refused(self):
        self.backup.parent.mkdir(parents=True)
        self.backup.mkdir()
        before = self.before()
        with self.assertRaises(FileExistsError):
            self.run_update(True)
        self.assertEqual(self.before(), before)
        self.assertEqual(list(self.backup.iterdir()), [])
        self.assertFalse(self.report.exists())

    def test_existing_report_not_overwritten(self):
        self.report.parent.mkdir(parents=True)
        self.report.write_bytes(b'private existing report')
        before = self.before()
        with self.assertRaises(FileExistsError):
            self.run_update(True)
        self.assertEqual(self.report.read_bytes(), b'private existing report')
        self.assertEqual(self.before(), before)
        self.assertFalse(self.backup.exists())

    def test_links_junctions_in_tree_and_input_ancestors_refused(self):
        alias = self.workspace / 'junction'
        if os.name == 'nt':
            subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(alias), str(self.stage.parent)],
                           capture_output=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            alias.symlink_to(self.stage.parent, target_is_directory=True)
        try:
            self.assert_preflight_refuses(staged=alias / 'Songs')
        finally:
            if os.name == 'nt':
                alias.rmdir()  # Remove only this fixture junction, never its contents.
            else:
                alias.unlink()
        linked = self.runtime / 'UserData/nested-link'
        if os.name == 'nt':
            subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(linked), str(self.source)],
                           capture_output=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            linked.symlink_to(self.source, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, 'Links/junctions'):
                self.run_update(True)
            self.assertFalse(self.backup.exists())
        finally:
            if os.name == 'nt':
                linked.rmdir()
            else:
                linked.unlink()

    def test_hardlinked_user_file_refused(self):
        original = self.runtime / 'UserData/preferences.json'
        linked = self.runtime / 'UserData/hardlink.json'
        os.link(original, linked)
        try:
            with self.assertRaisesRegex(ValueError, 'Hard-linked'):
                self.run_update(True)
            self.assertFalse(self.backup.exists())
        finally:
            linked.unlink()

    def test_any_qinban_including_unknown_path_blocks_preflight(self):
        before = self.before()
        for apply in (False, True):
            for path in (str(self.runtime / 'QinBan.exe'), str(self.workspace / 'unrelated/QinBan.exe'), None):
                with self.subTest(apply=apply, path=path):
                    self.process_probe.return_value = [{'Id': 123, 'Path': path}]
                    with self.assertRaisesRegex(RuntimeError, 'ALL QinBan'):
                        self.run_update(apply)
                    self.assertEqual(self.before(), before)
                    self.assertFalse(self.backup.exists())
                    self.assertFalse(self.report.exists())

    def test_process_probe_failure_fails_closed(self):
        self.process_probe.side_effect = subprocess.TimeoutExpired('fixture probe', 30)
        self.assert_preflight_refuses(subprocess.TimeoutExpired)

    def test_process_race_after_preflight_blocks_before_score_copy(self):
        before = self.before()
        self.process_probe.side_effect = [[], [{'Id': 123, 'Path': None}]]
        with self.assertRaisesRegex(RuntimeError, 'ALL QinBan'):
            self.run_update(True)
        self.assertEqual(before, self.before())
        self.assertEqual(self.result()['copiedNewFilesPreserved'], [])

    def test_process_race_before_first_switch_preserves400_inactive_files(self):
        before = self.before()
        self.process_probe.side_effect = [[], [], [], [{'Id': 123, 'Path': None}]]
        with self.assertRaises(RuntimeError):
            self.run_update(True)
        self.assert_old_catalogs(before)
        result = self.result()
        self.assertEqual(len(result['newInactiveFilesPreserved']), 400)
        self.assertTrue(result['manualRecoveryRequired'])

    def test_process_race_between_targets_records_partial_active_state_no_kill(self):
        calls = 0
        def active():
            nonlocal calls
            calls += 1
            return [{'Id': 123, 'Path': None}] if calls >= 5 else []
        self.process_probe.side_effect = active
        with self.assertRaises(RuntimeError):
            self.run_update(True)
        result = self.result()
        self.assertEqual(result['catalogStates']['runtime']['state'], 'staged-332')
        self.assertEqual(result['catalogStates']['source']['state'], 'original-132')
        self.assertTrue(any(not item['restored'] for item in result['rollback']))
        self.assertTrue(result['manualRecoveryRequired'])

    def test_full_inventory_race_before_copy_refuses_both_changes(self):
        original = update._write_json_new
        def write_then_race(path, value):
            original(path, value)
            (self.source / 'private-extra.txt').write_bytes(b'new source edit during preflight')
            (self.runtime / 'UserData/preferences.json').write_bytes(b'new runtime edit during preflight')
        before = self.before()
        with mock.patch.object(update, '_write_json_new', side_effect=write_then_race):
            with self.assertRaises(ValueError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        self.assertEqual(self.result()['copiedNewFilesPreserved'], [])
        self.assertEqual((self.source / 'private-extra.txt').read_bytes(), b'new source edit during preflight')
        self.assertEqual((self.runtime / 'UserData/preferences.json').read_bytes(), b'new runtime edit during preflight')

    def test_source_and_stage_races_during_copy_refused_before_switch(self):
        original = update._copy_exclusive
        def copy_then_race(src, dst, *args, **kwargs):
            original(src, dst, *args, **kwargs)
            if dst == self.source / self.new_rows[-1][2]:
                (self.source / 'nested/keep.txt').write_bytes(b'user changed source file')
                (self.stage / self.new_rows[0][2]).write_bytes(b'stage changed after copy')
        before = self.before()
        with mock.patch.object(update, '_copy_exclusive', side_effect=copy_then_race):
            with self.assertRaises(ValueError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        self.assertEqual(len(self.result()['newInactiveFilesPreserved']), 400)

    def test_unplanned_files_and_empty_directories_not_silently_accepted(self):
        original = update._copy_exclusive
        def copy_then_race(src, dst, *args, **kwargs):
            original(src, dst, *args, **kwargs)
            if dst == self.source / self.new_rows[-1][2]:
                (self.runtime / 'UserData/new-file.bin').write_bytes(b'new user file')
                (self.source / 'new-empty-directory').mkdir()
        before = self.before()
        with mock.patch.object(update, '_copy_exclusive', side_effect=copy_then_race):
            with self.assertRaises(ValueError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        self.assertEqual((self.runtime / 'UserData/new-file.bin').read_bytes(), b'new user file')
        self.assertTrue((self.source / 'new-empty-directory').is_dir())

    def test_copy_collision_race_never_overwrites_or_claims_user_file(self):
        original = update._copy_exclusive
        user_file = self.runtime / 'Songs' / self.new_rows[0][2]
        def race_before_copy(src, dst, *args, **kwargs):
            if dst == user_file:
                user_file.write_bytes(b'concurrent user file')
            return original(src, dst, *args, **kwargs)
        before = self.before()
        with mock.patch.object(update, '_copy_exclusive', side_effect=race_before_copy):
            with self.assertRaises(FileExistsError):
                self.run_update(True)
        self.assertEqual(user_file.read_bytes(), b'concurrent user file')
        self.assert_old_catalogs(before)
        self.assertEqual(self.result()['copiedNewFilesPreserved'], [])

    def test_partial_copy_failure_in_second_target_retains_every_created_file(self):
        original = shutil.copyfileobj
        partial = self.source / self.new_rows[2][2]
        def copying(inp, out, *args, **kwargs):
            if Path(out.name) == partial:
                out.write(b'PARTIAL FIXTURE, NOT A SCORE')
                raise OSError('injected disk full on source copy')
            return original(inp, out, *args, **kwargs)
        before = self.before()
        with mock.patch.object(update.shutil, 'copyfileobj', side_effect=copying):
            with self.assertRaises(OSError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        result = self.result()
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(len(result['copiedNewFilesPreserved']), 203)
        failures = [item for item in result['copiedNewFilesPreserved'] if not item['complete']]
        self.assertEqual(len(failures), 1)
        self.assertFalse(failures[0]['matchesExpected'])
        self.assertEqual(partial.read_bytes(), b'PARTIAL FIXTURE, NOT A SCORE')
        self.assertFalse(result['automaticResumeSupported'])
        self.assertTrue(result['manualRecoveryRequired'])
        with self.assertRaises(FileExistsError):
            self.run_update(True, backup=self.workspace / 'another-backup', report=self.workspace / 'another-report.json')
        self.assertTrue(partial.exists())

    def test_second_target_switch_failure_rolls_back_runtime_catalogue_only(self):
        original = update.atomic_copy
        before = self.before()
        def switching(src, dst, **kwargs):
            if dst == self.source / 'catalog.db' and src == self.stage / 'catalog.db':
                raise OSError('injected second switch failure')
            return original(src, dst, **kwargs)
        with mock.patch.object(update, 'atomic_copy', side_effect=switching):
            with self.assertRaises(OSError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        result = self.result()
        self.assertTrue(all(item['restored'] for item in result['rollback']))
        self.assertEqual(len(result['newInactiveFilesPreserved']), 400)
        for path in result['newInactiveFilesPreserved']:
            self.assertTrue(Path(path).is_file())
        self.assertEqual((self.runtime / 'UserData/library.db').read_bytes(), b'NOT SQLITE; HASH ONLY')

    def test_error_after_both_replacements_restores_both_never_userdata(self):
        original = update.atomic_copy
        before = self.before()
        user_file = self.runtime / 'UserData/preferences.json'
        source_file = self.source / 'private-extra.txt'
        def switching(src, dst, **kwargs):
            original(src, dst, **kwargs)
            if dst == self.source / 'catalog.db' and src == self.stage / 'catalog.db':
                user_file.write_bytes(b'new user edit after both switches')
                source_file.write_bytes(b'new source edit after both switches')
                raise OSError('injected post-replace exception')
        with mock.patch.object(update, 'atomic_copy', side_effect=switching):
            with self.assertRaises(OSError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        result = self.result()
        self.assertEqual(len(result['rollback']), 2)
        self.assertTrue(all(item['restored'] for item in result['rollback']))
        self.assertEqual(user_file.read_bytes(), b'new user edit after both switches')
        self.assertEqual(source_file.read_bytes(), b'new source edit after both switches')
        self.assertEqual(len(result['newInactiveFilesPreserved']), 400)

    def test_readonly_replace_failure_restores_original_hash_and_permissions(self):
        for target in (self.runtime / 'Songs/catalog.db', self.source / 'catalog.db'):
            os.chmod(target, stat.S_IREAD)
        before = self.before()
        with mock.patch.object(update.os, 'replace', side_effect=PermissionError('injected refusal')):
            with self.assertRaises(PermissionError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        for target in (self.runtime / 'Songs/catalog.db', self.source / 'catalog.db'):
            self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE)
        self.assertEqual(len(self.result()['newInactiveFilesPreserved']), 400)
        self.assertFalse(any(path.name.startswith('catalog-switch-') for path in (self.runtime / 'Songs').iterdir()))

    def test_exception_after_os_replace_side_effect_is_guardedly_rolled_back(self):
        original, injected = os.replace, False
        before = self.before()
        def replace(src, dst):
            nonlocal injected
            original(src, dst)
            if not injected:
                injected = True
                raise OSError('injected exception after actual replace')
        with mock.patch.object(update.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.run_update(True)
        self.assert_old_catalogs(before)
        self.assertTrue(all(item['restored'] for item in self.result()['rollback']))

    def test_later_user_catalogue_not_overwritten_during_rollback(self):
        original = update.atomic_copy
        user_catalogue = b'new concurrent user catalogue bytes'
        def switching(src, dst, **kwargs):
            if dst == self.source / 'catalog.db' and src == self.stage / 'catalog.db':
                (self.runtime / 'Songs/catalog.db').write_bytes(user_catalogue)
                raise OSError('injected user catalogue race')
            return original(src, dst, **kwargs)
        with mock.patch.object(update, 'atomic_copy', side_effect=switching):
            with self.assertRaises(OSError):
                self.run_update(True)
        self.assertEqual((self.runtime / 'Songs/catalog.db').read_bytes(), user_catalogue)
        result = self.result()
        self.assertEqual(result['catalogStates']['runtime']['state'], 'changed-unknown')
        self.assertTrue(any(not item['restored'] for item in result['rollback']))

    def test_corrupted_backup_prevents_unsafe_rollback_and_is_reported(self):
        original = update.atomic_copy
        def switching(src, dst, **kwargs):
            if dst == self.source / 'catalog.db' and src == self.stage / 'catalog.db':
                (self.backup / 'runtime-catalog.db').write_bytes(b'corrupted backup')
                raise OSError('injected second switch failure')
            return original(src, dst, **kwargs)
        with mock.patch.object(update, 'atomic_copy', side_effect=switching):
            with self.assertRaises(OSError):
                self.run_update(True)
        result = self.result()
        self.assertEqual(result['catalogStates']['runtime']['state'], 'staged-332')
        self.assertTrue(any('backup hash changed' in item.get('error', '') for item in result['rollback']))
        self.assertTrue(result['manualRecoveryRequired'])

    def test_rollback_os_failure_reports_unresolved_active_target(self):
        original = update.atomic_copy
        def switching(src, dst, **kwargs):
            if src == self.backup / 'runtime-catalog.db':
                raise PermissionError('injected rollback refusal')
            if dst == self.source / 'catalog.db' and src == self.stage / 'catalog.db':
                raise OSError('injected source switch failure')
            return original(src, dst, **kwargs)
        with mock.patch.object(update, 'atomic_copy', side_effect=switching):
            with self.assertRaises(OSError):
                self.run_update(True)
        result = self.result()
        self.assertEqual(result['catalogStates']['runtime']['state'], 'staged-332')
        self.assertEqual(result['catalogStates']['source']['state'], 'original-132')
        self.assertTrue(any('rollback refusal' in item.get('error', '') for item in result['rollback']))
        self.assertEqual(len(result['copiedNewFilesPreserved']), 400)

    def test_second_apply_cannot_overwrite_original_evidence(self):
        self.run_update(True)
        before, report, backup = self.before(), self.report.read_bytes(), update.snapshot(self.backup)
        with self.assertRaises(FileExistsError):
            self.run_update(True)
        self.assertEqual(self.before(), before)
        self.assertEqual(self.report.read_bytes(), report)
        self.assertEqual(update.snapshot(self.backup), backup)

    def test_cli_contract_defaults_to_preflight_and_reports_failures(self):
        args = ['--staged-songs', str(self.stage), '--runtime', str(self.runtime),
                '--source-songs', str(self.source), '--backup', str(self.backup), '--report', str(self.report)]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(update.main(args), 0)
        self.assertIn('DRY-RUN-PASS', out.getvalue())
        self.assertFalse(self.backup.exists())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(update.main(args + ['--apply']), 1)
        self.assertIn('FAILED', err.getvalue())
        self.assertFalse(self.backup.exists())


class ProcessAndParsingTests(unittest.TestCase):
    def test_process_probe_never_filters_other_or_unknown_paths(self):
        values = [{'Id': 10, 'Path': 'C:/other/QinBan.exe'}, {'Id': 11, 'Path': None}]
        with mock.patch.object(update.os, 'name', 'nt'), mock.patch.object(update.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps(values)
            self.assertEqual(update.active_instances(), values)
            command = run.call_args.args[0][-1]
            self.assertIn('Get-Process -Name QinBan', command)
            self.assertNotIn('Stop-Process', command)
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_args.kwargs['timeout'], 30)
            run.return_value.stdout = '[]'
            self.assertEqual(update.active_instances(), [])
            run.return_value.stdout = json.dumps(values[1])
            self.assertEqual(update.active_instances(), [values[1]])
            for invalid in ('', 'null', '{}', '[{"Path":null}]', 'not-json'):
                run.return_value.stdout = invalid
                with self.assertRaises((ValueError, RuntimeError)):
                    update.active_instances()

    def test_non_windows_probe_fails_closed(self):
        with mock.patch.object(update.os, 'name', 'posix'):
            with self.assertRaises(RuntimeError):
                update.active_instances()

    def test_windows_flat_resource_names_and_ambiguous_json_rejected(self):
        for path in ('../x.json', 'nested/x.json', 'nested\\x.json', 'C:x.json',
                     'NUL.json', 'COM1.json', 'x.json ', 'x?.json', 'x\x00.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                update._relative_score(path)
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ValueError):
                update._json(raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
