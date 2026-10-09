"""Pinned public POP909 acquisition; 100 real MIDI files, no music invention.
Only writes a NEW evidence directory. Never touches runtime/UserData.
"""
import argparse, collections, hashlib, json, sys, time, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
from discover_pop_metadata import parse_index
from smf_reference import parse_smf

COMMIT = 'd83e6edba6872a704f5d3b8b32f5cb540088dae6'
REPO = 'music-x-lab/POP909-Dataset'
HEADERS = {'User-Agent': 'QinBan-local-score-intake', 'Accept': 'application/vnd.github+json'}
PRIORITY = '''晴天|修炼爱情|小幸运|光年之外|消愁|大鱼|那些年|丑八怪|绅士|演员|十年|爱情转移|红豆|匆匆那年|勇气|宁夏|暖暖|会呼吸的痛|突然好想你|倔强|温柔|隐形的翅膀|贝加尔湖畔|传奇|父亲写的散文诗|曾经的你|蓝莲花|不分手的恋爱|一万个理由|体面|凉凉|追光者|纸短情长|9420|123我爱你|后来|成全|很爱很爱你|背对背拥抱|曹操|一千年以后|那些你很冒险的梦|东风破|菊花台|蒲公英的约定|花海|夜曲|简单爱|青花瓷|不能说的秘密|倒带|柠檬草的味道|易燃易爆炸|小半|光|山水之间|庐州月|清明雨上|有何不可|第一次|童话|星语心愿|伤心太平洋|忽然之间|盛夏的果实|盛夏|像我这样的人|不将就|李白|模特|泡沫|逆战|最美的太阳|开始懂了|遇见|克卜勒|月半小夜曲|吻别|吻得太逼真|一生有你|同桌的你|起风了|说散就散|成都|南山南|平凡之路|告白气球|稻香|七里香'''.split('|')
ARTISTS = '''周杰伦|林俊杰|蔡依林|薛之谦|陈奕迅|王菲|张学友|邓紫棋|田馥甄|许嵩|毛不易|李荣浩|梁静茹|张杰|许巍|孙燕姿|陈粒|张韶涵|李健|刘若英|五月天|汪苏泷|胡夏|光良|莫文蔚|刘德华|杨宗纬|张惠妹|陶喆|周深|郑源|任贤齐|许飞|陈鸿宇|赵雷|鹿先森乐队|张碧晨|刘瑞琦|朴树|庄心妍|麦小兜|新乐尘符'''.split('|')

def now(): return datetime.now(timezone.utc).isoformat()
def digest(b): return hashlib.sha256(b).hexdigest().upper()
def git_digest(b): return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def write_json(path, obj):
    with path.open('x', encoding='utf-8') as f: json.dump(obj, f, ensure_ascii=False, indent=2)
def fetch(url, max_bytes, events):
    for attempt in range(1,4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
                data=r.read(max_bytes+1)
            if len(data)>max_bytes: raise ValueError('HTTP response exceeds budget')
            events.append({'url':url,'attempt':attempt,'status':'OK','bytes':len(data),'sha256':digest(data),'at':now()})
            return data
        except Exception as e:
            events.append({'url':url,'attempt':attempt,'status':'ERROR','error':repr(e),'at':now()})
            if attempt==3: raise
            time.sleep(attempt)

def select(rows):
    by_title=collections.defaultdict(list)
    for row in rows: by_title[row['title']].append(row)
    chosen=[]; used_titles={'日不落','美人鱼','美人魚'}; counts=collections.Counter(); misses=[]
    def add(row):
        if row['title'] in used_titles or counts[row['artists'][0]]>=7: return False
        chosen.append(row); used_titles.add(row['title']); counts[row['artists'][0]]+=1; return True
    for title in PRIORITY:
        candidates=by_title.get(title,[])
        # Prefer an artist explicitly recorded by the source, never rewrite a cover identity.
        candidates=sorted(candidates,key=lambda r:(r['artists'][0] not in ARTISTS,int(r['sourceIndexId'])))
        if candidates: add(candidates[0])
        else: misses.append(title)
        if len(chosen)==100:break
    while len(chosen)<100:
        before=len(chosen)
        for artist in ARTISTS:
            available=[r for r in rows if r['artists']==[artist] and r['title'] not in used_titles]
            if available: add(available[0])
            if len(chosen)==100:break
        if len(chosen)==before:raise ValueError('Not enough unique selected titles')
    return chosen, misses

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('output',type=Path); ap.add_argument('--resume',action='store_true'); args=ap.parse_args(); root=args.output.resolve()
    if root.exists() and not args.resume: raise FileExistsError('Refusing to overwrite evidence: '+str(root))
    root.mkdir(parents=True,exist_ok=args.resume); events=[]; rejected=[]
    if (root/'manifest.json').exists(): raise FileExistsError('Completed intake is immutable')
    if args.resume:
        previous=json.loads((root/'acquisition-failure.json').read_text(encoding='utf-8'))
        events=previous['httpEvents']
        for filename,kind in [('source-tree.json','/git/trees/'),('source-archive.zip','codeload.github.com')]:
            expected=next(e['sha256'] for e in events if e['status']=='OK' and kind in e['url'])
            if digest((root/filename).read_bytes())!=expected: raise ValueError('Resume source hash mismatch: '+filename)
    try:
        tree_data=(root/'source-tree.json').read_bytes() if args.resume else fetch(f'https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1',4*1024*1024,events)
        tree=json.loads(tree_data)
        if tree.get('truncated'):raise ValueError('Truncated source tree')
        if not args.resume: (root/'source-tree.json').write_bytes(tree_data)
        blobs={x['path']:x for x in tree['tree'] if x['type']=='blob'}
        archive_url=f'https://codeload.github.com/{REPO}/zip/{COMMIT}'
        print('Downloading official pinned archive...',flush=True)
        # A single bounded archive transfer avoids 100 API calls and rate-limit churn.
        if not args.resume:
            archive_data=fetch(archive_url,128*1024*1024,events)
            (root/'source-archive.zip').write_bytes(archive_data); del archive_data
        with zipfile.ZipFile(root/'source-archive.zip') as z:
            prefix=f'POP909-Dataset-{COMMIT}/'
            def extract_verified(rel, target):
                info=z.getinfo(prefix+rel)
                expected=blobs[rel]
                if info.file_size>2*1024*1024 or info.file_size!=expected['size']:raise ValueError('Source size mismatch: '+rel)
                data=z.read(info)
                if git_digest(data)!=expected['sha']:raise ValueError('Git blob mismatch: '+rel)
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    if not args.resume or target.read_bytes()!=data: raise ValueError('Existing source mismatch: '+str(target))
                else:
                    with target.open('xb') as f:f.write(data)
                return data
            index_data=extract_verified('POP909/index.xlsx',root/'index.xlsx')
            extract_verified('README.md',root/'source-README.md'); extract_verified('LICENSE',root/'source-LICENSE.txt')
            rows=parse_index(index_data); chosen,misses=select(rows); songs=[]
            chosen_ids={r['sourceIndexId'] for r in chosen}; priority_artists={a:i for i,a in enumerate(ARTISTS)}
            reserves=sorted([r for r in rows if r['sourceIndexId'] not in chosen_ids], key=lambda r:(priority_artists.get(r['artists'][0],999),int(r['sourceIndexId'])))
            used_titles={'日不落','美人鱼','美人魚'}; counts=collections.Counter()
            for candidate in chosen+reserves:
                if len(songs)==100:break
                if candidate['title'] in used_titles or counts[candidate['artists'][0]]>=7:continue
                sid=candidate['sourceIndexId']; rel=f'POP909/{sid}/{sid}.mid'
                data=extract_verified(rel,root/'midi'/f'{sid}.mid')
                try:
                    reference=parse_smf(data)
                    if reference['durationKinds']<2:raise ValueError('Source has no duration variety')
                    if reference['lengthMs']<90_000:raise ValueError('Short source fragment (<90sec); not selected for this batch')
                except Exception as e:
                    rejected.append({'id':sid,'title':candidate['title'],'error':repr(e),'bundled':False})
                    print(f'REJECT {sid} {candidate["title"]}: {e}',flush=True)
                    continue
                ref_path=root/'references'/f'{sid}.json';ref_path.parent.mkdir(exist_ok=True)
                if ref_path.exists():
                    if json.loads(ref_path.read_text(encoding='utf-8'))!=reference:raise ValueError('Existing reference mismatch: '+sid)
                else: write_json(ref_path,reference)
                used_titles.add(candidate['title']);counts[candidate['artists'][0]]+=1
                songs.append({'id':sid,'title':candidate['title'],'artist':candidate['artists'][0],
                    'midiPath':str(root/'midi'/f'{sid}.mid'),'referencePath':str(ref_path),
                    'sourceUrl':f'https://github.com/{REPO}/blob/{COMMIT}/{rel}',
                    'metadataSource':f'https://github.com/{REPO}/blob/{COMMIT}/POP909/index.xlsx',
                    'sourceSha256':digest(data),'githubBlobSha':blobs[rel]['sha'],
                    'languageTags':[],'languageStatus':'not-stated-by-source','album':'',
                    'durationMs':reference['lengthMs'],'notes':len(reference['notes']),
                    'tempoChanges':reference['tempoChanges'],'durationKinds':reference['durationKinds'],
                    'completeness':'unknown','musicReview':'not-reviewed','gameReview':'not-tested','redistributionVerified':False})
                print(f"{len(songs):03d}/100 {sid} {candidate['title']} - {candidate['artists'][0]} ({len(reference['notes'])} notes)",flush=True)
        if len(songs)!=100 or len({s['title'] for s in songs})!=100:raise ValueError('Expected 100 unique new titles')
        write_json(root/'manifest.json',{'sourceCommit':COMMIT,'retrievedAtUtc':now(),'provider':'POP909','songs':songs})
        write_json(root/'acquisition-report.json',{'status':'PASS','selectedRealMidiFiles':100,'distinctSelectedTitles':100,
            'sourceArchiveContainsOtherCandidates':True,'otherCandidatesBundled':False,'extractedRejectedCandidates':len(rejected),
            'sourceArchiveSha256':digest((root/'source-archive.zip').read_bytes()),'indexSha256':digest(index_data),
            'totalSelectedMidiBytes':sum(Path(s['midiPath']).stat().st_size for s in songs),
            'artists':dict(collections.Counter(s['artist'] for s in songs)),
            'preferredTitlesAbsentFromIndex':misses,'rejected':rejected,'httpEvents':events,
            'limitations':['Source timing is not independent musical accuracy certification.',
                'No source language/album/recording identities inferred. No today-trending claim.',
                'Repository license is recorded; underlying works redistribution is unverified. Local personal library only.']})
        print('PASS: 100 real source MIDI files + independent timing references; no runtime changed.',flush=True)
    except Exception as e:
        write_json(root/('acquisition-resume-failure.json' if args.resume else 'acquisition-failure.json'),{'status':'FAIL','error':repr(e),'rejected':rejected,'httpEvents':events,'at':now()})
        raise
if __name__=='__main__': main()
