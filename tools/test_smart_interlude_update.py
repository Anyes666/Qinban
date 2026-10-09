"""Deterministic updater protection tests; fake files in the isolated batch, never real EXEs."""
import contextlib, io, json, sys, unittest, uuid
from pathlib import Path
from unittest.mock import patch
import update_smart_interludes as update
from update_builtin_library import sha, snapshot

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.root=update.BATCH / ('deploy-fixture-'+uuid.uuid4().hex)
        self.root.mkdir();self.repo=self.root/'repo';self.batch=self.repo/'.validation';self.runtime=self.root/'runtime';self.backup=self.root/'backup'
        for p in [self.repo,self.batch/'publish',self.runtime/'Songs',self.runtime/'UserData',self.backup]:p.mkdir(parents=True,exist_ok=True)
        (self.runtime/'QinBan.exe').write_bytes(b'old-fake-executable');(self.backup/'QinBan-before-smart-interludes.exe').write_bytes(b'old-fake-executable')
        (self.batch/'publish/QinBan.exe').write_bytes(b'new-fake-executable');(self.repo/'SMART-INTERLUDES.md').write_text('feature',encoding='utf-8')
        (self.runtime/'Songs/catalog.db').write_bytes(b'protected catalogue');(self.runtime/'Songs/score.json').write_bytes(b'protected score')
        (self.runtime/'UserData/library.db').write_bytes(b'protected user bytes')
        (self.backup/'before.json').write_text(json.dumps({str(p):sha(p) for p in (self.runtime/'Songs').iterdir()}),encoding='utf-8')
        self.patcher=patch.multiple(update,WORKSPACE=self.root,REPO=self.repo,BATCH=self.batch,RUNTIME=self.runtime,BACKUP=self.backup);self.patcher.start();self.addCleanup(self.patcher.stop)
    def run_update(self,apply=False,instances=None):
        self.report=self.batch/'result.json'
        argv=['update','--report',str(self.report)]+(['--apply'] if apply else [])
        with patch.object(sys,'argv',argv),patch.object(update,'active_instances',return_value=instances or []),contextlib.redirect_stdout(io.StringIO()):return update.main()
    def test_preflight_no_writes(self):
        before=snapshot(self.runtime);self.assertEqual(self.run_update(),0);self.assertEqual(before,snapshot(self.runtime));self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['status'],'PREFLIGHT_READY')
    def test_apply_preserves_scores_and_userdata(self):
        before=snapshot(self.runtime);self.assertEqual(self.run_update(True),0)
        after=snapshot(self.runtime);self.assertEqual(after['UserData/library.db'],before['UserData/library.db']);self.assertEqual(after['Songs/catalog.db'],before['Songs/catalog.db']);self.assertEqual(after['Songs/score.json'],before['Songs/score.json']);self.assertNotEqual(after['QinBan.exe'],before['QinBan.exe']);self.assertTrue((self.runtime/'智能衔接说明.md').is_file())
    def test_unknown_elevated_process_blocks_apply(self):
        before=snapshot(self.runtime);self.assertEqual(self.run_update(True,[{'Id':1,'Path':None}]),3);self.assertEqual(before,snapshot(self.runtime))
    def test_changed_exe_is_never_overwritten(self):
        (self.runtime/'QinBan.exe').write_bytes(b'user-updated-exe');before=snapshot(self.runtime)
        with self.assertRaises(ValueError):self.run_update(True)
        self.assertEqual(before,snapshot(self.runtime))
    def test_changed_score_is_never_overwritten(self):
        (self.runtime/'Songs/score.json').write_bytes(b'user-modified-score');before=snapshot(self.runtime)
        with self.assertRaises(ValueError):self.run_update(True)
        self.assertEqual(before,snapshot(self.runtime))
    def test_existing_doc_is_never_overwritten(self):
        (self.runtime/'智能衔接说明.md').write_bytes(b'user-document');before=snapshot(self.runtime)
        with self.assertRaises(ValueError):self.run_update(True)
        self.assertEqual(before,snapshot(self.runtime))
    def test_race_new_process_prevents_switch(self):
        before=snapshot(self.runtime);argv=['update','--report',str(self.batch/'result.json'),'--apply']
        with patch.object(sys,'argv',argv),patch.object(update,'active_instances',side_effect=[[],[{'Id':2,'Path':None}]]):
            with self.assertRaises(RuntimeError):update.main()
        self.assertEqual(before,snapshot(self.runtime));self.assertEqual(json.loads((self.batch/'result.json').read_text(encoding='utf-8'))['status'],'FAILED_NO_EXE_CHANGE')
    def test_document_failure_rolls_exe_back(self):
        before=snapshot(self.runtime);real_open=Path.open;target=self.runtime/'智能衔接说明.md'
        def opening(path,*args,**kwargs):
            if path==target:raise PermissionError('simulated new-document failure')
            return real_open(path,*args,**kwargs)
        with patch.object(Path,'open',opening):
            with self.assertRaises(PermissionError):self.run_update(True)
        self.assertEqual(before,snapshot(self.runtime));self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['status'],'FAILED_ROLLED_BACK')
if __name__=='__main__':unittest.main(verbosity=2)
