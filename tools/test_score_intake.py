"""All fixtures are self-authored test bytes: NOT songs, licenses or certificates.
The test-only approved/synthetic=false declarations exercise administrative branches;
they NEVER establish real copyright, actual human review or golden-song eligibility.
"""
import ast
import csv
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from audit_score_intake import REQUIRED,MAX_FILE_BYTES,MAX_NOTES,MAX_DURATION_MS,audit,digest,resolve,validate_notes
from smf_reference import parse_smf

DISCLAIMER='self-authored administrative fixture; NOT a song, license, certificate or actual human review; real songs added = 0'


def vlq(value):
    parts=[value&127];value>>=7
    while value: parts.insert(0,(value&127)|128);value>>=7
    return bytes(parts)


def midi_fixture(pitch=60, tag=''):
    # One local test note, 500 ms long, with a 250 ms terminal rest. NOT a song.
    track=b''
    if tag:
        payload=tag.encode('ascii');track+=b'\x00\xff\x01'+vlq(len(payload))+payload
    track+=b'\x00\x90'+bytes([pitch,90])+vlq(480)+b'\x80'+bytes([pitch,0])+vlq(240)+b'\xff\x2f\x00'
    return b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+struct.pack('>I',len(track))+track


class IntakeTests(unittest.TestCase):
    def setUp(self):
        evidence=os.environ.get('INTAKE_TEST_EVIDENCE_DIR')
        self.tmp=None
        if evidence:
            base=Path(evidence).resolve();base.mkdir(parents=True,exist_ok=True)
            self.root=Path(tempfile.mkdtemp(prefix=self._testMethodName+'-',dir=base)).resolve()
        else:
            self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.manifest=self.root/'manifest.csv';self.serial=0;self.audits=0

    def tearDown(self):
        if self.tmp: self.tmp.cleanup()  # Only our generated temporary fixtures, never supplied sources.

    def write(self, rows):
        with self.manifest.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=REQUIRED);writer.writeheader();writer.writerows(rows)

    def put(self, relative, data):
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def get(self, relative): return json.loads((self.root/relative).read_text(encoding='utf-8'))

    def record(self, synthetic=False, work='fixture-work', edition=None, pitch=60, tag=''):
        self.serial+=1;prefix=f'record-{self.serial:03d}/';edition=edition or f'fixture-edition-{self.serial}'
        source=prefix+'source.mid';(self.root/prefix).mkdir();(self.root/source).write_bytes(midi_fixture(pitch,tag))
        sh=digest(self.root/source);reference=parse_smf((self.root/source).read_bytes());reference['synthetic']=False
        ref=prefix+'reference.json';self.put(ref,reference)
        song=dict(version=1,title='Self-authored one-note fixture - NOT a song',bpm=120,lengthMs=reference['lengthMs'],notes=reference['notes'],
                  provenance=dict(artists=['test-only identity, not a singer'],languageTags=['zxx'],synthetic=synthetic,sourceSha256=sh,timingStatus='source-compared',workId='',editionId='',
                                  redistributionVerified=False,musicReview='not-reviewed',gameReview='not-tested'))
        normalized=prefix+'normalized.json';self.put(normalized,song);nh=digest(self.root/normalized)
        timing=prefix+'timing.json';self.put(timing,dict(status='PASS',sourceSha256=sh,normalizedSha256=nh,referenceSha256=digest(self.root/ref),
                                                      referenceFile=ref,maxErrorMs=0,notes=len(reference['notes'])))
        row=dict(zip(REQUIRED,[work,edition,'NOT a song - administrative fixture','test-only','test-only',f'test:{work}',
                 'https://example.invalid/no-song','TEST-ONLY-NO-LICENSE','full-work',source,sh,normalized,timing,
                 prefix+'rights.json',prefix+'music.json',prefix+'game.json']))
        for field in ('rights_review','music_review','game_review'):
            self.put(row[field],dict(decision='approved',reviewer='test-only placeholder - NOT a real reviewer',reviewedAt='2026-10-05',
                notes=DISCLAIMER,sha256=sh if field=='rights_review' else nh,workId=work,editionId=edition,
                permissions=['normalize','arrange','bundle'],completeness='full-work',reviewedLengthMs=reference['lengthMs'],
                instrumentId='windsong',gameVersion='test-only NOT game-tested',playOptions={'instrumentId':'windsong'}))
        return row

    def rebind_normalized(self, row):
        nh=digest(self.root/row['normalized_file']);timing=self.get(row['timing_report']);timing['normalizedSha256']=nh;self.put(row['timing_report'],timing)
        for field in ('music_review','game_review'):
            evidence=self.get(row[field]);evidence['sha256']=nh;self.put(row[field],evidence)

    def rebind_reference(self, row):
        timing=self.get(row['timing_report']);timing['referenceSha256']=digest(self.root/timing['referenceFile']);self.put(row['timing_report'],timing)

    def rebind_source(self, row):
        sh=digest(self.root/row['source_file']);row['source_sha256']=sh
        song=self.get(row['normalized_file']);song['provenance']['sourceSha256']=sh;self.put(row['normalized_file'],song)
        timing=self.get(row['timing_report']);timing['sourceSha256']=sh;self.put(row['timing_report'],timing)
        rights=self.get(row['rights_review']);rights['sha256']=sh;self.put(row['rights_review'],rights);self.rebind_normalized(row)

    def run_audit(self, rows=None):
        if rows is not None: self.write(rows)
        inputs=[p for p in self.root.rglob('*') if p.is_file() and not p.name.startswith('audit-')]
        before={str(p.relative_to(self.root)):digest(p) for p in inputs}
        result=audit(self.manifest,self.root)
        after={str(p.relative_to(self.root)):digest(p) for p in inputs}
        self.assertEqual(before,after,'audit must not modify or delete source/evidence files')
        self.audits+=1
        self.put(f'audit-{self.audits:03d}.json',dict(fixtureDisclaimer=DISCLAIMER,inputHashesBefore=before,inputHashesAfter=after,report=result))
        return result

    def rejected(self, rows, reason=None):
        result=self.run_audit(rows);self.assertEqual(result['evidenceCompleteDistinctWorks'],0)
        self.assertEqual(result['rejectedEditions'],len(rows));self.assertEqual(result['rejectedRows'],result['rows'])
        if reason: self.assertIn(reason,'; '.join(result['rows'][0]['errors']))
        return result

    def cli(self, manifest=None, output='cli-report.json'):
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('audit_score_intake.py').resolve()),
                               str(manifest or self.manifest),str(self.root),str(self.root/output)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.put(f'cli-log-{self.serial}-{output}.json',dict(fixtureDisclaimer=DISCLAIMER,exitCode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        self.assertNotIn('Traceback',result.stderr);return result

    def test_empty_is_zero_not_successful_golden_batch(self):
        result=self.run_audit([])
        self.assertEqual((result['candidateEditions'],result['evidenceCompleteEditions'],result['evidenceCompleteDistinctWorks']), (0,0,0))
        self.assertEqual(result['rejectedRows'],[]);self.assertEqual(result['fatalErrors'],[])

    def test_completeness_is_not_certification(self):
        result=self.run_audit([self.record()]);self.assertEqual(result['evidenceCompleteDistinctWorks'],1)
        self.assertEqual(result['evidenceCompleteEditions'],1);self.assertIn('not independently certified',result['certification'])

    def test_normalized_formal_identity_required_without_artist_language_guessing(self):
        for change in ({'artists':[]}, {'languageTags':[]}, {'languageTags':['und']}, {'languageTags':['cmn','und']}, {'artists':None}, {'artists':['A','A']}, {'artists':['']}, {'languageTags':['bad_tag']}, {'languageTags':['EN','en']}, {'album':None}, {'versionLabel':None}):
            with self.subTest(change=change):
                row=self.record();song=self.get(row['normalized_file']);song['provenance'].update(change)
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_formal_legacy_artist_and_mixed_languages_are_compatible_declarations(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance'].update(artists=[],artist='test-only declared singer',languageTags=['cmn','en'],album='test-only album',versionLabel='test-only edition')
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteDistinctWorks'],1)

    def test_identity_artists_utf16_over_limit_rejected(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['artists']=['\U00020BB7'*129]
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.rejected([row],'invalid singer artists list')

    def test_identity_artists_utf16_exact_limit_accepted(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['artists']=['\U00020BB7'*128]
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        result=self.run_audit([row])
        self.assertEqual((result['evidenceCompleteEditions'],result['rejectedEditions']),(1,0))

    def test_identity_version_label_utf16_over_limit_rejected(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['versionLabel']='\U00020BB7'*129
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.rejected([row],'invalid metadata: versionlabel')

    def test_identity_version_label_utf16_exact_limit_accepted(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['versionLabel']='\U00020BB7'*128
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        result=self.run_audit([row])
        self.assertEqual((result['evidenceCompleteEditions'],result['rejectedEditions']),(1,0))

    def test_identity_album_utf16_over_limit_rejected(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['album']='\U00020BB7'*501
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.rejected([row],'invalid metadata: album')

    def test_identity_album_utf16_exact_limit_accepted(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance']['album']='\U00020BB7'*500
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        result=self.run_audit([row])
        self.assertEqual((result['evidenceCompleteEditions'],result['rejectedEditions']),(1,0))

    def test_source_without_identity_still_converts_but_not_formally_complete(self):
        row=self.record();source='record-001/source.json';self.put(source,{'version':1,'notes':[{'pitch':60,'startMs':0,'durationMs':500}],'lengthMs':750})
        row['source_file']=source;self.rebind_source(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteDistinctWorks'],1)


    def test_invalid_source_bytes_cannot_be_saved_by_pass_declarations(self):
        for raw in (b'NOT a MIDI/song',b'MThd',midi_fixture()[:25],midi_fixture()[:-2]):
            with self.subTest(raw=raw.hex()):
                row=self.record();(self.root/row['source_file']).write_bytes(raw);self.rebind_source(row)
                self.rejected([row],'source_file')

    def test_version_structure_and_key_index_rejected(self):
        for change in ({'version':None},{'version':True},{'version':2},{'songNotes':[]},{'notes':None},{'notes':{}},{'notes':[]},{'notes':[None]},{'notes':['note']}):
            with self.subTest(change=change):
                row=self.record();song=self.get(row['normalized_file']);song.update(change)
                if change=={'version':None}: song.pop('version')
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_each_required_note_field(self):
        for field in ('pitch','startMs','durationMs'):
            with self.subTest(field=field):
                row=self.record();song=self.get(row['normalized_file']);song['notes'][0].pop(field)
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row],field if field=='pitch' else 'required')

    def test_note_numeric_types_and_limits(self):
        cases=[('pitch',v) for v in (-1,128,60.0,True,'60',None)]
        cases += [('startMs',v) for v in (-1,True,'0',None,float('nan'),float('inf'),1e400,10**400,MAX_DURATION_MS)]
        cases += [('durationMs',v) for v in (0,-1,60001,False,'500',None,float('-inf'))]
        cases += [('track',v) for v in (-1,1024,False,0.0)] + [('velocity',v) for v in (0,128,True,90.0)] + [('percussion',v) for v in (0,'false',None)]
        for field,value in cases:
            with self.subTest(field=field,value=value):
                row=self.record();song=self.get(row['normalized_file']);song['notes'][0][field]=value
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_optional_note_fields_use_application_defaults(self):
        row=self.record();song=self.get(row['normalized_file'])
        for field in ('track','velocity','percussion'): song['notes'][0].pop(field)
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_full_length_finite_and_terminal_rest_preserved(self):
        for value in (None,0,-1,100,500,MAX_DURATION_MS+1,True,'750',float('nan'),float('inf')):
            with self.subTest(value=value):
                row=self.record();song=self.get(row['normalized_file']);song['lengthMs']=value
                if value is None: song.pop('lengthMs')
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row])

    def test_synthetic_markers_across_all_json_scores(self):
        for target in ('normalized_file','referenceFile','source-json'):
            for value in (True,'false',0,None):
                with self.subTest(target=target,value=value):
                    row=self.record()
                    if target=='referenceFile':
                        path=self.get(row['timing_report'])['referenceFile'];data=self.get(path);data['synthetic']=value
                        self.put(path,data);self.rebind_reference(row)
                    elif target=='source-json':
                        data=self.get(row['normalized_file']);data['provenance']['synthetic']=value
                        row['source_file']=row['source_file'].replace('.mid','.json');self.put(row['source_file'],data);self.rebind_source(row)
                    else:
                        data=self.get(row[target]);data['provenance']['synthetic']=value;self.put(row[target],data);self.rebind_normalized(row)
                    self.rejected([row],'synthetic')

    def test_missing_synthetic_uses_application_false_default(self):
        row=self.record();song=self.get(row['normalized_file']);song['provenance'].pop('synthetic')
        self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_notes_json_source_supported_with_existing_optional_fields(self):
        row=self.record();song=self.get(row['normalized_file']);source=dict(notes=song['notes'],lengthMs=song['lengthMs'])
        for field in ('track','velocity','percussion'): source['notes'][0].pop(field)
        row['source_file']=row['source_file'].replace('.mid','.json');self.put(row['source_file'],source);self.rebind_source(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_existing_metadata_budgets(self):
        for field,value in [('title','x'*181),('bpm',19),('bpm',401),('bpm',True),('warnings',[None]),('provenance',None)]:
            with self.subTest(field=field):
                row=self.record();song=self.get(row['normalized_file']);song[field]=value
                self.put(row['normalized_file'],song);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_numeric_budget_boundaries(self):
        note={'pitch':127,'startms':MAX_DURATION_MS-60000,'durationms':60000,'track':1023,'velocity':127,'percussion':True}
        self.assertEqual(validate_notes({'notes':[note],'lengthms':MAX_DURATION_MS})['length'],MAX_DURATION_MS)
        repeated={'pitch':0,'startms':0,'durationms':1}
        self.assertEqual(len(validate_notes({'notes':[repeated]*MAX_NOTES,'lengthms':1})['notes']),MAX_NOTES)
        with self.assertRaises(ValueError): validate_notes({'notes':[repeated]*(MAX_NOTES+1),'lengthms':1})

    def test_uppercase_properties_match_application(self):
        row=self.record();song=self.get(row['normalized_file'])
        song={k.upper():v for k,v in song.items()};song['NOTES']=[{k.upper():v for k,v in note.items()} for note in song['NOTES']]
        song['PROVENANCE']={k.upper():v for k,v in song['PROVENANCE'].items()};self.put(row['normalized_file'],song);self.rebind_normalized(row)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_source_hash_and_normalized_tampering(self):
        row=self.record();row['source_sha256']='0'*64;self.rejected([row],'source hash mismatch')
        row=self.record();song=self.get(row['normalized_file']);song['notes'][0]['pitch']=61
        self.put(row['normalized_file'],song);self.rejected([row],'hash-bound timing')

    def test_reference_path_and_report_hash_binding(self):
        for key,value in [('referenceFile',None),('referenceFile','../outside.json'),('referenceFile',str(self.root/'absolute.json')),
                          ('referenceFile','missing.json'),('referenceSha256',None),('referenceSha256','0'*64),('sourceSha256','0'*64),('normalizedSha256','0'*64)]:
            with self.subTest(key=key,value=value):
                row=self.record();timing=self.get(row['timing_report']);timing[key]=value
                self.put(row['timing_report'],timing);self.rejected([row])

    def test_reference_actual_note_and_length_comparison(self):
        for key,value in [('pitch',61),('startMs',1),('durationMs',499),('track',1),('velocity',91),('percussion',True),('lengthMs',500)]:
            with self.subTest(key=key):
                row=self.record();path=self.get(row['timing_report'])['referenceFile'];ref=self.get(path)
                if key=='lengthMs': ref[key]=value
                else: ref['notes'][0][key]=value
                self.put(path,ref);self.rebind_reference(row);self.rejected([row],'reference')

    def test_pass_report_does_not_replace_source_reference_check(self):
        row=self.record();song=self.get(row['normalized_file']);song['notes'][0]['pitch']=61;self.put(row['normalized_file'],song)
        path=self.get(row['timing_report'])['referenceFile'];ref=self.get(path);ref['notes'][0]['pitch']=61;self.put(path,ref)
        self.rebind_normalized(row);self.rebind_reference(row);self.rejected([row],'reference pitch')

    def test_timing_counts_tolerance_and_recomputed_error(self):
        for key,value in [('notes',True),('notes',1.0),('notes',0),('notes',2),('maxErrorMs',True),('maxErrorMs',-1),
                          ('maxErrorMs',.003),('maxErrorMs',.001),('maxErrorMs',float('nan')),('status','FAIL')]:
            with self.subTest(key=key,value=value):
                row=self.record();timing=self.get(row['timing_report']);timing[key]=value;self.put(row['timing_report'],timing);self.rejected([row],'timing_report')

    def test_sub_tolerance_timing_difference_and_error_report(self):
        row=self.record();song=self.get(row['normalized_file']);song['notes'][0]['startMs']=.001;self.put(row['normalized_file'],song)
        self.rebind_normalized(row);timing=self.get(row['timing_report']);timing['maxErrorMs']=.001;self.put(row['timing_report'],timing)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_review_declaration_bytes_and_types(self):
        for field in ('rights_review','music_review','game_review'):
            for key,value in [('decision','pending'),('reviewer','   '),('reviewer',[]),('reviewedAt','not-a-date'),('notes',{}),('sha256','0'*64)]:
                with self.subTest(field=field,key=key):
                    row=self.record();data=self.get(row[field]);data[key]=value;self.put(row[field],data);self.rejected([row],field)

    def test_review_work_and_edition_scope(self):
        for field in ('rights_review','music_review','game_review'):
            for key,value in [('workId',None),('workId','different-work'),('workId',['fixture-work']),('editionId','different-edition')]:
                with self.subTest(field=field,key=key):
                    row=self.record();data=self.get(row[field]);data[key]=value
                    if value is None: data.pop(key)
                    self.put(row[field],data);self.rejected([row],'scope')
        for field in ('music_review','game_review'):
            row=self.record();data=self.get(row[field]);data.pop('editionId');self.put(row[field],data);self.rejected([row],'editionId')

    def test_work_scope_rights_can_cover_multiple_editions(self):
        row=self.record();data=self.get(row['rights_review']);data.pop('editionId');self.put(row['rights_review'],data)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_music_full_work_review_range(self):
        for key,value in [('completeness','fragment'),('reviewedLengthMs',None),('reviewedLengthMs',500),('reviewedLengthMs',True),('reviewedLengthMs',float('inf'))]:
            with self.subTest(key=key,value=value):
                row=self.record();data=self.get(row['music_review']);data[key]=value;self.put(row['music_review'],data);self.rejected([row],'music_review')

    def test_rights_permissions_are_not_a_string_or_unscoped_claim(self):
        for value in ('normalize arrange bundle',{'normalize':1,'arrange':1,'bundle':1},['normalize','arrange'],['normalize','arrange','bundle',{}]):
            row=self.record();data=self.get(row['rights_review']);data['permissions']=value;self.put(row['rights_review'],data);self.rejected([row],'permissions')

    def test_game_review_target_version_and_options(self):
        for key,value in [('instrumentId',' '),('instrumentId',[]),('gameVersion',''),('playOptions',[]),('playOptions',{'instrumentId':'floral'})]:
            row=self.record();data=self.get(row['game_review']);data[key]=value;self.put(row['game_review'],data);self.rejected([row],'game_review')

    def test_normalized_nonempty_work_identity_must_match(self):
        for key in ('workId','editionId'):
            row=self.record();data=self.get(row['normalized_file']);data['provenance'][key]='other-id'
            self.put(row['normalized_file'],data);self.rebind_normalized(row);self.rejected([row],'identity mismatch')

    def test_work_id_change_cannot_reuse_old_reviews(self):
        row=self.record();row['work_id']='claimed-other-work';self.rejected([row],'workId scope')

    def test_same_bytes_cannot_be_different_works_even_with_fresh_declarations(self):
        first=self.record(work='work-a');second=self.record(work='work-b')
        # Both records have freshly scoped TEST-ONLY declarations; not copyright evidence.
        self.rejected([first,second],'conflicting work_id')
        self.rejected([second,first],'conflicting work_id')

    def test_duplicate_edition_id_rejects_all_conflicts(self):
        first=self.record(edition='same-edition');second=self.record(edition='same-edition',pitch=62)
        self.rejected([first,second],'duplicate edition_id')

    def test_same_work_different_arrangements_count_once(self):
        result=self.run_audit([self.record(),self.record(pitch=62)])
        self.assertEqual(result['evidenceCompleteEditions'],2);self.assertEqual(result['evidenceCompleteDistinctWorks'],1)

    def test_duplicate_arrangement_not_an_extra_edition(self):
        first=self.record();second=self.record(tag='different bytes but same notes')
        data=self.get(second['normalized_file']);data['title']='Metadata change only - NOT a song';self.put(second['normalized_file'],data);self.rebind_normalized(second)
        result=self.run_audit([first,second]);self.assertEqual(result['evidenceCompleteEditions'],1)
        self.assertEqual(result['evidenceCompleteDistinctWorks'],1);self.assertIn('duplicate arrangement',result['rejectedRows'][0]['errors'][0])

    def test_same_music_different_work_and_source_metadata_rejected(self):
        first=self.record(work='work-a');second=self.record(work='work-b',tag='different source metadata')
        self.assertNotEqual(first['source_sha256'],second['source_sha256']);self.rejected([first,second],'same content identity')

    def test_platform_identity_overlap_rejected_for_different_works(self):
        first=self.record(work='work-a');second=self.record(work='work-b',pitch=62)
        first['platform_ids']='test:shared;test:other';second['platform_ids']='test:third;test:shared'
        self.rejected([first,second],'platforms identity')

    def test_legacy_license_and_fragment_rejections(self):
        for field,value in [('license','unverified'),('completeness','fragment'),('platform_ids','test:a;;test:b'),('artist',' '),('title','x'*4097)]:
            row=self.record();row[field]=value;self.rejected([row],'metadata')

    def test_malformed_json_unicode_and_duplicate_properties_are_reported(self):
        for raw in (b'{bad',b'\xff',b'null',b'[]',b'"string"',b'{"version":1,"Version":1}'):
            with self.subTest(raw=raw):
                row=self.record();(self.root/row['normalized_file']).write_bytes(raw);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_wrong_top_level_evidence_types_are_reported(self):
        for field in ('timing_report','rights_review','music_review','game_review','referenceFile'):
            row=self.record();path=self.get(row['timing_report'])['referenceFile'] if field=='referenceFile' else row[field]
            self.put(path,[])
            if field=='referenceFile': self.rebind_reference(row)
            self.rejected([row],'top level')

    def test_depth_budget_and_recursion_are_rejections_not_crashes(self):
        for depth in (33,1100):
            row=self.record();song=json.dumps(self.get(row['normalized_file']))
            raw=song[:-1]+',"extra":'+('['*depth)+'0'+(']'*depth)+'}'
            (self.root/row['normalized_file']).write_text(raw,encoding='utf-8');self.rebind_normalized(row)
            self.rejected([row],'normalized_file')

    def test_traversal_missing_and_absolute_paths_rejected(self):
        row=self.record()
        for value in ('../outside',str(self.root/row['source_file']),'missing.mid',''):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): resolve(self.root,value)
        row['music_review']='../outside.json';self.rejected([row],'music_review')

    def test_individual_file_budget_is_enforced(self):
        path=self.root/'large.mid'
        with path.open('wb') as stream: stream.truncate(MAX_FILE_BYTES)
        self.assertEqual(resolve(self.root,'large.mid'),path)
        with path.open('r+b') as stream: stream.truncate(MAX_FILE_BYTES+1)
        with self.assertRaisesRegex(ValueError,'16 MiB'): resolve(self.root,'large.mid')
        row=self.record();row['source_file']='large.mid';row['source_sha256']=digest(path);self.rejected([row],'16 MiB')

    def test_manifest_bad_header_utf8_and_csv_report_fatal(self):
        for raw in (b'wrong,header\n',b'\xff',(','.join(REQUIRED)+'\n"unterminated').encode()):
            self.manifest.write_bytes(raw);result=self.run_audit()
            self.assertTrue(result['fatalErrors']);self.assertEqual(result['evidenceCompleteDistinctWorks'],0)

    def test_csv_extra_and_missing_cells_are_row_rejections(self):
        row=self.record();self.write([row])
        with self.manifest.open('a',encoding='utf-8') as stream: stream.write('too,few\n')
        result=self.run_audit();self.assertEqual(result['rejectedEditions'],1);self.assertEqual(result['evidenceCompleteEditions'],1)
        self.write([row]);raw=self.manifest.read_text(encoding='utf-8-sig').rstrip('\n')+',extra\n'
        self.manifest.write_text(raw,encoding='utf-8');result=self.run_audit();self.assertEqual(result['rejectedEditions'],1)

    def test_over_10000_editions_rejects_batch_without_partial_success(self):
        good=self.record();empty=dict.fromkeys(REQUIRED,'')
        self.write([good]+[dict(empty,edition_id=f'empty-{i}') for i in range(10000)])
        result=self.run_audit();self.assertEqual(result['candidateEditions'],10000)
        self.assertEqual(result['evidenceCompleteDistinctWorks'],0);self.assertEqual(result['rejectedEditions'],10000)
        self.assertIn('10,000',result['fatalErrors'][0])

    def test_manifest_size_budget_reports_fatal(self):
        with self.manifest.open('wb') as stream: stream.truncate(MAX_FILE_BYTES+1)
        result=self.run_audit();self.assertIn('16 MiB',result['fatalErrors'][0])

    def test_missing_manifest_is_fatal(self):
        result=self.run_audit();self.assertTrue(result['fatalErrors']);self.assertEqual(result['rows'],[])

    def test_cli_empty_zero_and_refuses_overwrite(self):
        self.write([]);first=self.cli();self.assertEqual(first.returncode,0)
        path=self.root/'cli-report.json';before=digest(path);second=self.cli();self.assertEqual(second.returncode,1)
        self.assertIn('Refusing to overwrite',second.stderr);self.assertEqual(digest(path),before)
        self.assertEqual(self.get('cli-report.json')['evidenceCompleteDistinctWorks'],0)

    def test_cli_rejected_rows_and_fatal_reports(self):
        self.write([self.record(True)]);result=self.cli();self.assertEqual(result.returncode,1);self.assertIn('REJECT line 2',result.stdout)
        self.assertEqual(len(self.get('cli-report.json')['rejectedRows']),1)
        self.manifest.write_text('bad,header\n',encoding='utf-8');result=self.cli(output='fatal-report.json')
        self.assertEqual(result.returncode,1);self.assertTrue(self.get('fatal-report.json')['fatalErrors'])

    def test_cli_output_creation_failure_is_explicit(self):
        self.write([]);(self.root/'not-a-directory').write_text('local test marker',encoding='utf-8')
        result=self.cli(output='not-a-directory/report.json');self.assertEqual(result.returncode,1)
        self.assertIn('could not create new report',result.stderr)

    def test_optional_application_metadata_types(self):
        for field,value in [('keyInstrumentId','unknown'),('keyInstrumentId',None),('keyInstrumentId',[]),('keyInstrumentId',True)]:
            row=self.record();data=self.get(row['normalized_file']);data[field]=value
            self.put(row['normalized_file'],data);self.rebind_normalized(row);self.rejected([row],'keyInstrumentId')
        for value in ('not-a-date',{},True):
            row=self.record();data=self.get(row['normalized_file']);data['provenance']['retrievedAt']=value
            self.put(row['normalized_file'],data);self.rebind_normalized(row);self.rejected([row],'normalized_file')

    def test_reference_cannot_bridge_two_out_of_tolerance_endpoints(self):
        row=self.record();data=self.get(row['normalized_file']);data['notes'][0]['startMs']=.004
        self.put(row['normalized_file'],data);self.rebind_normalized(row)
        path=self.get(row['timing_report'])['referenceFile'];ref=self.get(path);ref['notes'][0]['startMs']=.002
        self.put(path,ref);self.rebind_reference(row);timing=self.get(row['timing_report']);timing['maxErrorMs']=.002
        self.put(row['timing_report'],timing);self.rejected([row],'reference onset')

    def test_same_source_content_cannot_be_two_works_via_timing_rounding(self):
        first=self.record(work='work-a');second=self.record(work='work-b',tag='metadata-only')
        data=self.get(second['normalized_file']);data['notes'][0]['startMs']=.001
        self.put(second['normalized_file'],data);self.rebind_normalized(second)
        timing=self.get(second['timing_report']);timing['maxErrorMs']=.001;self.put(second['timing_report'],timing)
        self.rejected([first,second],'sourceContent identity')

    def test_same_source_content_rounding_does_not_add_an_edition(self):
        first=self.record();second=self.record(tag='metadata-only')
        data=self.get(second['normalized_file']);data['notes'][0]['startMs']=.001
        self.put(second['normalized_file'],data);self.rebind_normalized(second)
        timing=self.get(second['timing_report']);timing['maxErrorMs']=.001;self.put(second['timing_report'],timing)
        result=self.run_audit([first,second]);self.assertEqual(result['evidenceCompleteEditions'],1)
        self.assertEqual(result['rejectedEditions'],1)

    def test_source_json_format_not_inferred_from_extension(self):
        for data in ({'version':2,'notes':[{}]}, {'songNotes':[]}, {'notes':[{}]}, []):
            row=self.record();row['source_file']=row['source_file'].replace('.mid','.json')
            self.put(row['source_file'],data);self.rebind_source(row);self.rejected([row],'source_file')

    def test_all_bound_hashes_accept_lowercase_hex(self):
        row=self.record();row['source_sha256']=row['source_sha256'].lower()
        for field in ('timing_report','rights_review','music_review','game_review'):
            data=self.get(row[field])
            for key in ('sha256','sourceSha256','normalizedSha256','referenceSha256'):
                if key in data: data[key]=data[key].lower()
            self.put(row[field],data)
        self.assertEqual(self.run_audit([row])['evidenceCompleteEditions'],1)

    def test_contract_utf8_and_source_strings_are_not_question_damage(self):
        tools=Path(__file__).resolve().parent
        contract=(tools/'intake-audit-contract.md').read_bytes().decode('utf-8')
        self.assertIn('\u5165\u5e93\u884c\u653f\u8bc1\u636e\u5ba1\u8ba1',contract)
        self.assertGreater(sum('\u4e00'<=c<='\u9fff' for c in contract),1000)
        self.assertNotIn(chr(63),contract);self.assertNotIn(chr(0xfffd),contract)
        for name in ('audit_score_intake.py','test_score_intake.py'):
            source=(tools/name).read_bytes().decode('utf-8')
            for node in ast.walk(ast.parse(source)):
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    self.assertNotIn(chr(63)*2,node.value,(name,node.lineno))
                    self.assertNotIn(chr(0xfffd),node.value,(name,node.lineno))


if __name__=='__main__': unittest.main()
