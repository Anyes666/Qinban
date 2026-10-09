"""Deterministic score rhythm regressions; never send keyboard input."""
import json
import unittest
from pathlib import Path
from generate_builtin import parse, ROOT

class BuiltinRhythm(unittest.TestCase):
    def test_phrase_suffix_only_changes_last_note(self):
        n = parse("1155665:2 4433221:2", 96)
        self.assertEqual([x["startMs"] for x in n[:8]], [0,625,1250,1875,2500,3125,3750,5000])
        self.assertEqual([x["durationMs"] for x in n[:7]], [625]*6+[1250])
    def test_short_long_and_rest(self):
        n = parse("1:0.5 0:2 2:1.5", 120)
        self.assertEqual([x["startMs"] for x in n], [0,1250])
        self.assertEqual([x["durationMs"] for x in n], [250,750])
    def test_chord_suffix_applies_to_all_tones(self):
        n = parse("(135):2 1", 120)
        self.assertEqual([x["startMs"] for x in n], [0,0,0,1000])
        self.assertEqual([x["durationMs"] for x in n[:3]], [1000]*3)
    def test_pitch_octaves_and_mixed_duration(self):
        n = parse("1,1'1:3", 120)
        self.assertEqual([x["pitch"] for x in n], [48,72,60])
        self.assertEqual([x["durationMs"] for x in n], [500,500,1500])
    def test_thirty_sources_are_valid_and_manifest_matches(self):
        manifest = json.loads((ROOT/'tools/builtin-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest),30)
        for x in manifest:
            song=json.loads((ROOT/'Songs'/x['file']).read_text(encoding='utf-8'))
            self.assertEqual(song['title'],x['title'])
            self.assertEqual(len(song['notes']),x['notes'])
            self.assertTrue(all(n['durationMs']>0 for n in song['notes']))

if __name__=='__main__': unittest.main()
