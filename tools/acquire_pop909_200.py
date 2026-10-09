"""Select exactly 200 new POP909 editions from the existing pinned local archive.
No network, no invented notes, no live catalogue changes. Original inputs read-only.
"""
import argparse, collections, hashlib, json, re, shutil, sqlite3, unicodedata, zipfile
from datetime import datetime, timezone
from pathlib import Path
from acquire_pop909_100 import COMMIT, REPO, PRIORITY, ARTISTS
from discover_pop_metadata import parse_index
from smf_reference import parse_smf
from update_builtin_library import read_catalog

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OLD = ROOT / 'catalog-intake/pop100-2026-10-06'
RUNTIME = WORKSPACE / 'dist/QinBan-0.4.2-two-song-pilot-win-x64'

def sha(data): return hashlib.sha256(data).hexdigest().upper()
def blob(data): return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def canonical(title): return ''.join(c for c in unicodedata.normalize('NFKC',title).casefold() if not c.isspace() and unicodedata.category(c)[0] not in ('P','S'))
def work_key(title):
    # Preserve the original indexed display title. Strip only explicit edition/genre suffixes
    # when screening counts, so a DJ/original/new edition cannot pad this 200-song batch.
    title = unicodedata.normalize('NFKC', title).strip()
    title = re.sub(r'\s+DJ.*$', '', title, flags=re.I)
    title = re.sub(r'【(?:原版|新版|消音版)】$', '', title)
    title = re.sub(r'(?:原版|新版)$', '', title)
    title = re.sub(r'\s+民谣$', '', title)
    return canonical(title)
# Similar indexed titles with uncertain work identity are conservatively deferred,
# rather than counted as an extra song. This is not a claim of confirmed identity.
DEFER_WORK_IDENTITY = {'103': '与101《今夜你又在和谁约会》高度近似，独立作品身份未确认，本批不重复计数'}
def write(path,data):
    with path.open('x',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)
def now(): return datetime.now(timezone.utc).isoformat()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to((ROOT/'catalog-intake').resolve()) or out.exists():raise ValueError('Use a NEW intake directory inside catalog-intake')
    old_manifest=json.loads((OLD/'manifest.json').read_text(encoding='utf-8'))
    old_report=json.loads((OLD/'acquisition-report.json').read_text(encoding='utf-8'))
    if old_manifest['sourceCommit']!=COMMIT or sha((OLD/'source-archive.zip').read_bytes())!=old_report['sourceArchiveSha256']:raise ValueError('Pinned archive hash changed')
    baseline=read_catalog(RUNTIME/'Songs')
    if len(baseline)!=132:raise ValueError('Expected existing 132-entry runtime baseline')
    existing_ids=set(); used=set(); used_source_hashes=set()
    for _,(rel,_,meta) in baseline.items():
        used.add(work_key(meta['title']))
        source_hash = meta.get('provenance',{}).get('sourceSha256','').upper()
        if source_hash: used_source_hashes.add(source_hash)
        for alias in meta.get('provenance',{}).get('aliases',[]):used.add(work_key(alias))
        match=re.fullmatch(r'pop909-(\d{3})\.json',rel)
        if match:existing_ids.add(match.group(1))
    rows=parse_index((OLD/'index.xlsx').read_bytes())
    artists={value:i for i,value in enumerate(ARTISTS)}; titles={canonical(value):i for i,value in enumerate(PRIORITY)}
    # Prefer the same named artists/priority titles as the previous batch, then stable source IDs.
    candidates=sorted(rows,key=lambda r:(titles.get(canonical(r['title']),9999),artists.get(r['artists'][0],9999),int(r['sourceIndexId'])))
    tree=json.loads((OLD/'source-tree.json').read_text(encoding='utf-8'))
    if tree.get('truncated'):raise ValueError('Pinned source tree incomplete')
    blobs={v['path']:v['sha'] for v in tree['tree'] if v['type']=='blob'}
    out.mkdir();(out/'midi').mkdir();(out/'references').mkdir()
    rejected=[]; excluded=[]; chosen=[]; counts=collections.Counter()
    with zipfile.ZipFile(OLD/'source-archive.zip') as archive:
        prefix=f'POP909-Dataset-{COMMIT}/'
        for row in candidates:
            if len(chosen)==200:break
            sid=row['sourceIndexId']; title=row['title']; artist=row['artists'][0]
            if sid in DEFER_WORK_IDENTITY:
                excluded.append({'id':sid,'title':title,'reason':DEFER_WORK_IDENTITY[sid]});continue
            if sid in existing_ids or work_key(title) in used:
                excluded.append({'id':sid,'title':title,'reason':'existing id or edition-stripped work title/alias'});continue
            # Keep a broad artist mix in the new batch; not a current popularity ranking.
            if counts[artist]>=12:continue
            rel=f'POP909/{sid}/{sid}.mid'
            try:
                info=archive.getinfo(prefix+rel)
                if info.file_size>16*1024*1024:raise ValueError('source size over budget')
                data=archive.read(info)
                if blob(data)!=blobs.get(rel):raise ValueError('MIDI Git blob mismatch')
                if sha(data) in used_source_hashes:
                    excluded.append({'id':sid,'title':title,'reason':'duplicate source MIDI bytes'});continue
                reference=parse_smf(data)
                if reference['durationKinds']<2:raise ValueError('no source duration variety')
                if not 90000<=reference['lengthMs']<=1800000:raise ValueError('outside 90-second batch selection / 30-minute parser limit')
                if not 1<=len(reference['notes'])<=100000:raise ValueError('note count budget')
                if not any(n['track']==1 and not n['percussion'] for n in reference['notes']):raise ValueError('no source melody track')
            except Exception as e:
                rejected.append({'id':sid,'title':title,'error':repr(e),'bundled':False});continue
            midi=out/'midi'/f'{sid}.mid';ref=out/'references'/f'{sid}.json'
            with midi.open('xb') as f:f.write(data)
            write(ref,reference)
            chosen.append({'id':sid,'title':title,'artist':artist,'midiPath':str(midi),'referencePath':str(ref),
                'sourceUrl':f'https://github.com/{REPO}/blob/{COMMIT}/{rel}',
                'metadataSource':f'https://github.com/{REPO}/blob/{COMMIT}/POP909/index.xlsx',
                'sourceSha256':sha(data),'githubBlobSha':blobs[rel],'languageTags':[],
                'languageStatus':'not-stated-by-source','album':'','durationMs':reference['lengthMs'],
                'notes':len(reference['notes']),'tempoChanges':reference['tempoChanges'],'durationKinds':reference['durationKinds'],
                'completeness':'unknown','musicReview':'not-reviewed','gameReview':'not-tested','redistributionVerified':False})
            used.add(work_key(title));used_source_hashes.add(sha(data));counts[artist]+=1
            print(f'SELECT {len(chosen):03}/200 {sid} {title} - {artist}',flush=True)
    if len(chosen)!=200:raise ValueError('Insufficient accepted non-overlapping source titles; '+str(len(chosen)))
    write(out/'manifest.json',{'sourceCommit':COMMIT,'retrievedAtUtc':now(),'provider':'POP909','songs':chosen})
    write(out/'acquisition-report.json',{'status':'PASS_LOCAL_PINNED_ARCHIVE_EXTRACTION','selectedRealMidiFiles':200,
        'existingCatalogEntries':132,'expectedNewCatalogEntries':332,'sourceArchiveSha256':old_report['sourceArchiveSha256'],
        'sourceArchive':str(OLD/'source-archive.zip'),'sourceIndexSha256':sha((OLD/'index.xlsx').read_bytes()),
        'distinctSelectedCanonicalTitles':len({canonical(s['title']) for s in chosen}),
        'distinctEditionStrippedWorkKeys':len({work_key(s['title']) for s in chosen}),
        'distinctSourceHashes':len({s['sourceSha256'] for s in chosen}),'artists':dict(counts),
        'excludedExisting':excluded,'rejected':rejected,'httpCalls':0,'sourceArchiveUnchanged':True,
        'limitations':['Edition-stripped title/alias and source-byte screening excludes obvious overlaps; ambiguous near-titles deferred; not a cross-provider identity certification.',
          'Source timings are not human musical review or a complete-original-song certification.',
          'Unknown language/recording versions are not inferred; no today-trending claim.',
          'Repository license retained; underlying redistribution not certified; local personal library only.']})
    for name in ('source-LICENSE.txt','source-README.md'):
        shutil.copyfile(OLD/name,out/name)
    print('PASS 200 new local source MIDI editions and independent references; runtime unchanged')

if __name__=='__main__':main()