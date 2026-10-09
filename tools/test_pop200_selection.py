"""Deterministic selection regression; no network, catalogue changes or OS input."""
import json
import unittest
from pathlib import Path
from acquire_pop909_200 import work_key, canonical, DEFER_WORK_IDENTITY, RUNTIME
from update_builtin_library import read_catalog

ROOT=Path(__file__).resolve().parents[1]
INTAKE=ROOT/'catalog-intake/pop200-2026-10-06-v2'

class SelectionTests(unittest.TestCase):
    def test_canonical_nfkc_and_punctuation(self):
        self.assertEqual(canonical('Ａ B·C'), canonical('abc'))
    def test_dj_edition_not_counted_as_new_work(self):
        self.assertEqual(work_key('一剪梅 DJ费玉清'),work_key('一剪梅'))
    def test_explicit_editions_not_new_work(self):
        for edition in ['【原版】','【新版】','【消音版】','原版','新版']:
            self.assertEqual(work_key('初爱'+edition),work_key('初爱'))
    def test_theme_suffix_not_falsely_inferred_as_edition(self):
        self.assertNotEqual(work_key('我们 的 明天【重返20岁】'),work_key('我们的明天'))
    def test_meaningful_title_kept(self):
        self.assertEqual(work_key('下辈子不做女人'),canonical('下辈子不做女人'))
    def test_ambiguous_near_titles_deferred(self):
        self.assertIn('103',DEFER_WORK_IDENTITY)
        songs=json.loads((INTAKE/'manifest.json').read_text(encoding='utf8'))['songs']
        self.assertNotIn('103',{s['id'] for s in songs})
    def test_actual_batch_distinct_200(self):
        songs=json.loads((INTAKE/'manifest.json').read_text(encoding='utf8'))['songs']
        self.assertEqual(len(songs),200)
        for selector in [lambda s:s['id'],lambda s:work_key(s['title']),lambda s:s['sourceSha256']]:
            self.assertEqual(len({selector(s) for s in songs}),200)
    def test_batch_disjoint_from_original132(self):
        # Use the frozen real132 baseline: this remains valid after installation332.
        base=read_catalog(ROOT/'.validation/pop200-2026-10-06/baseline-Songs')
        keys={work_key(v[2]['title']) for v in base.values()}
        for value in base.values():
            keys.update(work_key(a) for a in value[2].get('provenance',{}).get('aliases',[]))
        songs=json.loads((INTAKE/'manifest.json').read_text(encoding='utf8'))['songs']
        self.assertEqual(len(base),132)
        self.assertFalse(keys & {work_key(s['title']) for s in songs})
    def test_no_fabricated_review_or_language(self):
        songs=json.loads((INTAKE/'manifest.json').read_text(encoding='utf8'))['songs']
        for s in songs:
            self.assertEqual(s['languageTags'],[])
            self.assertEqual(s['musicReview'],'not-reviewed')
            self.assertEqual(s['gameReview'],'not-tested')
            self.assertFalse(s['redistributionVerified'])
            self.assertTrue(s['title'].strip() and s['artist'].strip())

if __name__=='__main__':unittest.main(verbosity=2)
