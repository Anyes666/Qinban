"""Acquisition invariants and in-place deployment safeguards; no native input."""
import hashlib,json,os,shutil,sqlite3,stat,tempfile,unittest
from pathlib import Path
from unittest import mock
import acquire_pop909_100 as acquire
import update_builtin_library as update
from discover_pop_metadata import parse_index
from smf_reference import parse_smf
ROOT=Path(__file__).resolve().parents[1]
INTAKE=ROOT/'catalog-intake/pop100-2026-10-06'

class AcquisitionTests(unittest.TestCase):
    def test_index_selection_is_deterministic_and_excludes_existing_two(self):
        rows=parse_index((INTAKE/'index.xlsx').read_bytes())
        one,miss=acquire.select(rows);two,_=acquire.select(rows)
        self.assertEqual(one,two);self.assertEqual(len(one),100)
        self.assertEqual(len({r['title'] for r in one}),100)
        self.assertFalse({'日不落','美人鱼','美人魚'} & {r['title'] for r in one})
    def test_git_blob_digest_is_not_plain_file_sha1(self):
        data=b'hello\n';self.assertEqual(acquire.git_digest(data),'ce013625030ba8dba906f756967f9e9ca394464a')
        self.assertNotEqual(acquire.git_digest(data),hashlib.sha1(data).hexdigest())
    def test_all100_real_midi_have_reproducible_independent_references(self):
        manifest=json.loads((INTAKE/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['songs']),100)
        for row in manifest['songs']:
            with self.subTest(id=row['id']):
                data=Path(row['midiPath']).read_bytes(); ref=json.loads(Path(row['referencePath']).read_text(encoding='utf-8'))
                self.assertEqual(acquire.digest(data),row['sourceSha256']);self.assertEqual(acquire.git_digest(data),row['githubBlobSha'])
                self.assertEqual(parse_smf(data),ref);self.assertGreaterEqual(ref['lengthMs'],90_000)
                self.assertGreater(ref['durationKinds'],1);self.assertEqual(row['languageTags'],[])
    def test_rejections_are_reported_and_not_in_selected_manifest(self):
        report=json.loads((INTAKE/'acquisition-report.json').read_text(encoding='utf-8'))
        manifest=json.loads((INTAKE/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual({r['id'] for r in report['rejected']},{'098','511'})
        self.assertFalse({'098','511'} & {r['id'] for r in manifest['songs']})
        self.assertTrue(all(not r['bundled'] for r in report['rejected']))

class KeyDefaultsTests(unittest.TestCase):
    def test_only_pop909_transpose_change_is_accepted(self):
        from apply_pop100_key_defaults import ensure_transpose_only
        old={'builtin:pop909-001.json':('pop909-001.json','SHA',{'title':'song','options':{'transpose':0,'speed':1}})}
        new={'builtin:pop909-001.json':('pop909-001.json','SHA',{'title':'song','options':{'transpose':2,'speed':1}})}
        ensure_transpose_only(old,new)
    def test_source_resource_change_is_refused(self):
        from apply_pop100_key_defaults import ensure_transpose_only
        old={'builtin:pop909-001.json':('x.json','SHA',{'options':{'transpose':0}})}
        with self.assertRaises(ValueError):ensure_transpose_only(old,{'builtin:pop909-001.json':('x.json','OTHER',{'options':{'transpose':2}})})
    def test_old_teaching_default_cannot_be_changed(self):
        from apply_pop100_key_defaults import ensure_transpose_only
        old={'builtin:01.json':('01.json','SHA',{'options':{'transpose':0}})}
        with self.assertRaises(ValueError):ensure_transpose_only(old,{'builtin:01.json':('01.json','SHA',{'options':{'transpose':2}})})
    def test_title_or_speed_changes_are_refused(self):
        from apply_pop100_key_defaults import ensure_transpose_only
        old={'builtin:pop909-001.json':('x.json','SHA',{'title':'song','options':{'transpose':0,'speed':1}})}
        for obj in [{'title':'wrong','options':{'transpose':2,'speed':1}},{'title':'song','options':{'transpose':2,'speed':1.5}}]:
            with self.assertRaises(ValueError):ensure_transpose_only(old,{'builtin:pop909-001.json':('x.json','SHA',obj)})

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='qinban-pop100-update-test-');self.addCleanup(self.temp.cleanup)
        self.workspace=Path(self.temp.name).resolve();self.runtime=self.workspace/'dist/existing';self.source=self.workspace/'repo/Songs';self.stage=self.workspace/'stage/Songs'
        for p in [self.runtime/'Songs',self.source,self.stage]:p.mkdir(parents=True)
        (self.runtime/'QinBan.exe').write_bytes(b'FAKE EXECUTABLE FOR TEST ONLY')
        (self.runtime/'UserData').mkdir();(self.runtime/'UserData/private.txt').write_bytes(b'fake user content')
        old=[];fresh=[]
        for i in range(32):
            rel=f'old{i:02}.json';data=json.dumps({'title':f'old{i}','notes':[]}).encode();(self.stage/rel).write_bytes(data)
            obj={'title':f'old{i}','provenance':{'provider':'fixture'}};old.append((f'builtin:{rel}',rel,hashlib.sha256(data).hexdigest().upper(),json.dumps(obj)))
        for i in range(100):
            rel=f'pop909-{i:03}.json';data=json.dumps({'title':f'fixture{i}','notes':[]}).encode();(self.stage/rel).write_bytes(data)
            # Synthetic disposable tool-test bytes only; never delivered or counted as source songs.
            prov={'artists':['fixture artist'],'synthetic':False,'redistributionVerified':False,'musicReview':'not-reviewed','gameReview':'not-tested','timingStatus':'source-compared'}
            obj={'title':f'fixture{i}','provenance':prov};fresh.append((f'builtin:{rel}',rel,hashlib.sha256(data).hexdigest().upper(),json.dumps(obj)))
        self.rows=old+fresh
        self.catalog(self.stage,self.rows);self.catalog(self.runtime/'Songs',old);self.catalog(self.source,old[:30])
        for row in old:shutil.copyfile(self.stage/row[1],self.runtime/'Songs'/row[1])
        for row in old[:30]:shutil.copyfile(self.stage/row[1],self.source/row[1])
    def catalog(self,root,rows):
        with sqlite3.connect(root/'catalog.db') as db:
            db.execute('CREATE TABLE entries(id TEXT PRIMARY KEY,relative_path TEXT,content_hash TEXT,metadata_json TEXT)');db.executemany('INSERT INTO entries VALUES(?,?,?,?)',rows)
    def run_update(self,apply=False):
        return update.deploy(self.stage,self.runtime,self.source,self.workspace/'backup',self.workspace/'report.json',apply,check_process=False)
    def test_dry_run_does_not_change_runtime_or_source(self):
        a=update.snapshot(self.runtime);b=update.snapshot(self.source);r=self.run_update()
        self.assertEqual(r['status'],'DRY-RUN-PASS');self.assertEqual(a,update.snapshot(self.runtime));self.assertEqual(b,update.snapshot(self.source))
        self.assertFalse((self.workspace/'backup').exists())
    def test_apply_preserves_exe_userdata_old32_and_backs_up_catalogs(self):
        before=update.snapshot(self.runtime);r=self.run_update(True)
        self.assertEqual(r['status'],'PASS');self.assertTrue(r['exeUnchanged']);self.assertTrue(r['userDataUnchanged'])
        self.assertEqual(len(update.read_catalog(self.runtime/'Songs')),132);self.assertEqual(len(update.read_catalog(self.source)),132)
        for rel,digest in before.items():
            if rel!='Songs/catalog.db':self.assertEqual(update.sha(self.runtime/rel),digest)
        self.assertEqual(update.sha(self.workspace/'backup/runtime-catalog.db'),before['Songs/catalog.db'])
    def test_readonly_catalogue_updates_and_restores_readonly_flag(self):
        target=self.runtime/'Songs/catalog.db';os.chmod(target,stat.S_IREAD)
        r=self.run_update(True)
        self.assertEqual(r['status'],'PASS');self.assertTrue(r['runtimeCatalogReadOnly'])
        self.assertFalse(stat.S_IMODE(target.stat().st_mode)&stat.S_IWRITE)
    def test_readonly_replace_failure_restores_original_permission_and_catalogue(self):
        target=self.runtime/'Songs/catalog.db';os.chmod(target,stat.S_IREAD);before=update.sha(target)
        with mock.patch.object(update.os,'replace',side_effect=PermissionError('injected replacement refusal')):
            with self.assertRaises(PermissionError):self.run_update(True)
        self.assertEqual(update.sha(target),before);self.assertFalse(stat.S_IMODE(target.stat().st_mode)&stat.S_IWRITE)
    def test_resume_reuses_original_backup_without_overwriting_it(self):
        with mock.patch.object(update.os,'replace',side_effect=PermissionError('injected first attempt failure')):
            with self.assertRaises(PermissionError):self.run_update(True)
        backup_hash=update.sha(self.workspace/'backup/runtime-catalog.db')
        r=update.deploy(self.stage,self.runtime,self.source,self.workspace/'backup',self.workspace/'resume-report.json',True,check_process=False,resume=True)
        self.assertEqual(r['status'],'PASS');self.assertTrue(r['resumedOriginalBackup'])
        self.assertEqual(update.sha(self.workspace/'backup/runtime-catalog.db'),backup_hash)
    def test_resume_rejects_user_changes_since_original_backup(self):
        with mock.patch.object(update.os,'replace',side_effect=PermissionError('injected first attempt failure')):
            with self.assertRaises(PermissionError):self.run_update(True)
        (self.runtime/'UserData/private.txt').write_bytes(b'changed by user')
        with self.assertRaises(ValueError):update.deploy(self.stage,self.runtime,self.source,self.workspace/'backup',self.workspace/'resume-report.json',True,check_process=False,resume=True)
        self.assertEqual((self.runtime/'UserData/private.txt').read_bytes(),b'changed by user')
    def test_modified_existing_resource_is_refused_without_changes(self):
        (self.runtime/'Songs/old00.json').write_bytes(b'user modification');before=update.snapshot(self.runtime)
        with self.assertRaises(ValueError):self.run_update(True)
        self.assertEqual(before,update.snapshot(self.runtime));self.assertFalse((self.workspace/'backup').exists())
    def test_new_resource_path_collision_is_refused(self):
        (self.runtime/'Songs/pop909-000.json').write_bytes(b'user score same path')
        with self.assertRaises(ValueError):self.run_update(True)
        self.assertEqual((self.runtime/'Songs/pop909-000.json').read_bytes(),b'user score same path')
    def test_corrupted_stage_catalogue_is_refused(self):
        (self.stage/'catalog.db').write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):self.run_update(True)
    def test_changed_old_metadata_is_refused(self):
        with sqlite3.connect(self.stage/'catalog.db') as db:db.execute("UPDATE entries SET metadata_json=? WHERE id='builtin:old00.json'",(json.dumps({'title':'changed'}),))
        with self.assertRaises(ValueError):self.run_update(True)
    def test_atomic_failure_restores_prior_active_catalogue(self):
        before=update.snapshot(self.runtime);original=update.atomic_copy;calls=[]
        def fail_second(src,dst):
            calls.append(dst)
            if len(calls)==2:raise OSError('injected atomic replacement failure')
            original(src,dst)
        with mock.patch.object(update,'atomic_copy',side_effect=fail_second):
            with self.assertRaises(OSError):self.run_update(True)
        self.assertEqual(update.sha(self.runtime/'Songs/catalog.db'),before['Songs/catalog.db'])
        result=json.loads((self.workspace/'report.json').read_text(encoding='utf-8'));self.assertEqual(result['status'],'FAIL')
        self.assertTrue(result['rollback'][0]['restored']);self.assertTrue(result['newInactiveFilesPreserved'])
    def test_backup_inside_runtime_is_refused(self):
        with self.assertRaises(ValueError):update.deploy(self.stage,self.runtime,self.source,self.runtime/'backup',self.workspace/'report.json',True,check_process=False)
    def test_paths_outside_workspace_are_refused(self):
        with self.assertRaises(ValueError):update.deploy(self.stage,self.runtime,self.source,self.workspace.parent/'wrong-backup',self.workspace/'report.json',True,check_process=False)
    def test_running_instance_is_refused_without_stopping_it(self):
        before=update.snapshot(self.runtime)
        with mock.patch.object(update,'running_runtime',return_value=[{'Id':123,'Path':str(self.runtime/'QinBan.exe')}]):
            with self.assertRaises(RuntimeError):update.deploy(self.stage,self.runtime,self.source,self.workspace/'backup',self.workspace/'report.json',True)
        self.assertEqual(before,update.snapshot(self.runtime));self.assertFalse((self.workspace/'backup').exists())
    def test_second_apply_refuses_to_overwrite_backup_report(self):
        self.run_update(True)
        with self.assertRaises(FileExistsError):self.run_update(True)

if __name__=='__main__':unittest.main(verbosity=2)
