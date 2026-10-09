"""Independent source-byte/timing, catalogue and PCM audit of a passed POP100 build."""
import argparse, hashlib, json, math, sqlite3, wave
from collections import Counter
from pathlib import Path
import numpy as np
from smf_reference import parse_smf
from discover_pop_metadata import parse_index

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def ordered(notes):return sorted(notes,key=lambda n:(n.get('track',0),n['startMs'],n['pitch'],n['durationMs'],n.get('velocity',90)))
def audit(intake,stage):
    m=json.loads((intake/'manifest.json').read_text(encoding='utf-8')); report=json.loads((stage/'build-report.json').read_text(encoding='utf-8'))
    assert report['status'].startswith('PASS_SOURCE_COMPARED'), 'Build failed; never publish partial output'
    index={r['sourceIndexId']:r for r in parse_index((intake/'index.xlsx').read_bytes())}
    assert len(m['songs'])==100 and len(report['songs'])==100 and not report['syntheticFixture']
    assert report['nativeKeySendAttempts']==0 and not report['gameTested'] and not report['musicReviewed']
    assert all(report[k] for k in ['independentSourceTimingVerified','sourceFilesUnchanged','baselineFilesUnchanged','baselineMetadataUnchanged','normalizedRoundTripPreserved'])
    max_error=0.; total=0; rows=[]
    db=sqlite3.connect((stage/'Songs/catalog.db').resolve().as_uri()+'?mode=ro',uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    catalog={r[0]:json.loads(r[1]) for r in db.execute('SELECT id,metadata_json FROM entries')};db.close();assert len(catalog)==132
    for s in m['songs']:
        source=Path(s['midiPath']); normalized=stage/'Songs'/f"pop909-{s['id']}.json";data=json.loads(normalized.read_text(encoding='utf-8')); ref=parse_smf(source.read_bytes())
        assert sha(source)==s['sourceSha256']; assert data['title']==index[s['id']]['title']==s['title']
        assert data['provenance']['artists']==index[s['id']]['artists']==[s['artist']]
        assert data['provenance']['languageTags']==s['languageTags']==[]
        a,b=ordered(data['notes']),ordered(ref['notes']);assert len(a)==len(b)>0
        error=abs(data['lengthMs']-ref['lengthMs'])
        for x,y in zip(a,b):
            assert all(x.get(k,default)==y.get(k,default) for k,default in [('pitch',0),('track',0),('velocity',90),('percussion',False)])
            error=max(error,abs(x['startMs']-y['startMs']),abs(x['durationMs']-y['durationMs']))
        assert error<=.002;max_error=max(max_error,error);total+=len(a)
        entry=catalog[f"builtin:pop909-{s['id']}.json"]
        assert entry['resourceHash']==sha(normalized) and entry['hash']==s['sourceSha256']
        assert entry['options']['tracks']==[1], 'Default melody only; accompaniment remains optional'
        assert entry['provenance']==data['provenance']
        assert len({round(n['durationMs'],3) for n in a})>1
        assert not data['provenance']['synthetic'] and not data['provenance']['redistributionVerified']
        rows.append({'id':s['id'],'title':s['title'],'artist':s['artist'],'notes':len(a),'maxTimingErrorMs':error,'jsonBytes':normalized.stat().st_size})
    assert len(report['mappings'])==900 and all(v['valid'] for v in report['mappings'])
    assert len(report['drums'])==300 and all(v['blocked'] for v in report['drums'])
    samples=report['sampleIds'];assert len(samples)==len(set(samples))==5
    plans=sorted((stage/'sample-plans').glob('*.json'));assert len(plans)==45
    for file in plans:
        d=json.loads(file.read_text(encoding='utf-8'));assert d['id'] in samples
        source=json.loads((stage/'Songs'/f"pop909-{d['id']}.json").read_text(encoding='utf-8'))
        onsets={n['startMs'] for n in source['notes'] if n['track'] in d['options']['tracks'] and not n['percussion']}
        for note in d['plan']['notes']:assert note['startMs'] in onsets and note['soundMs']>0 and note['holdMs']>0
    waves=[]
    for item in report['waves']:
        file=stage/item['relativePath'];assert sha(file)==item['sha256'];assert item['isFragment']
        with wave.open(str(file),'rb') as w:
            assert w.getnchannels()==1 and w.getsampwidth()==2
            rate=w.getframerate();frames=w.getnframes();data=np.frombuffer(w.readframes(frames),dtype='<i2').astype(np.float64)
        duration=frames/rate;assert 0<duration<=30.0001
        rms=float(np.sqrt(np.mean(data**2)));peak=float(np.max(np.abs(data)));clipped=int(np.count_nonzero(np.abs(data)>=32760))
        assert rms>10 and peak>50, 'Silent WAV';assert clipped==0, 'Clipped WAV'
        waves.append({'file':str(file.resolve()),'sha256':sha(file),'seconds':duration,'rms':rms,'peak':peak,'clippedSamples':clipped,'audioPlayed':False})
    assert len(waves)==10
    return {'status':'PASS_INDEPENDENT_OUTPUT_AUDIT','sourceFiles':100,'catalogEntries':132,'sourceNotesCompared':total,'maxTimingErrorMs':max_error,
        'normalizedSongBytes':sum(r['jsonBytes'] for r in rows),'sourceSongBytes':sum(Path(s['midiPath']).stat().st_size for s in m['songs']),
        'sampleIds':samples,'detailedPlanChecks':45,'mappingChecks':900,'drumBlockedChecks':300,
        'sourceSongs':rows,'waves':waves,'musicReviewed':False,'realGameTested':False,'nativeKeySendAttempts':0}

def main():
    p=argparse.ArgumentParser();p.add_argument('--intake',type=Path,required=True);p.add_argument('--stage',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    if a.report.exists():raise FileExistsError('Immutable audit output already exists')
    r=audit(a.intake.resolve(),a.stage.resolve());a.report.parent.mkdir(parents=True,exist_ok=True)
    with a.report.open('x',encoding='utf-8') as f:json.dump(r,f,ensure_ascii=False,indent=2)
    print('PASS independent audit: 100 songs; '+str(r['sourceNotesCompared'])+' source notes; max timing error '+str(r['maxTimingErrorMs'])+' ms; WAV10 non-silent/non-clipped')
if __name__=='__main__':main()
