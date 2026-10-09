"""Deterministic independent evidence checks and read-only report generation (no production writes)."""
import collections,csv,hashlib,io,json,math,os,pathlib,sqlite3,statistics,wave
ROOT=pathlib.Path(__file__).resolve().parents[2]
TOOL=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'.validation/pop100-gap-diagnosis-2026-10-06'
checks=0

def check(ok,message):
    global checks
    checks+=1
    if not ok: raise AssertionError(message)

def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def new(name,data):
    check(name.startswith('mapping-'),'write scope')
    with (OUT/name).open('x',encoding='utf-8',newline='') as f:f.write(data)
def dump(name,data):new(name,json.dumps(data,ensure_ascii=False,indent=2))
def near(a,b):return abs(a-b)<=1e-5

def union(spans):
    out=[]
    for start,end in sorted(spans):
        if not out or start>out[-1][1]+1e-6:out.append([start,end])
        else:out[-1][1]=max(out[-1][1],end)
    return out

def intersection(a,b):
    return sum(max(0,min(x[1],y[1])-max(x[0],y[0])) for x in union(a) for y in union(b))

def rawgaps(spans,duration):
    u=union(spans);gaps=[(a[1],b[0]) for a,b in zip(u,u[1:])];longs=[(a,b) for a,b in gaps if b-a>=5000-1e-6]
    return {'countGe5s':len(longs),'totalGe5sMs':sum(b-a for a,b in longs),'maximumInternalMs':max([b-a for a,b in gaps],default=0),
      'leadingMs':u[0][0],'trailingMs':max(0,duration-u[-1][1]),'activeMs':sum(b-a for a,b in u)}

def csvnew(name,rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);new(name,stream.getvalue())

matrix=load(OUT/'mapping-results-verified.json'); initial=load(OUT/'mapping-results.json'); finalOld=load(OUT/'mapping-results-final.json')
focus=load(OUT/'mapping-focused-alltracks-verified.json'); focusOld=load(OUT/'mapping-focused-alltracks.json');changes=load(OUT/'mapping-key-onset-changes.json')
rows=matrix['matrix'];instruments=matrix['summary']['melodyInstruments'];bykey={(x['id'],x['instrument']):x for x in rows}
check(len(rows)==900 and len(bykey)==900,'900 unique rows');check(len(instruments)==9,'9 instruments')
songs={x['id']:x for x in rows};check(len(songs)==100,'100 distinct songs')
conn=sqlite3.connect((ROOT/'Songs/catalog.db').as_uri()+'?mode=ro',uri=True)
catalog={json.loads(x[0])['relativePath']:json.loads(x[0]) for x in conn.execute("SELECT metadata_json FROM entries WHERE relative_path LIKE 'pop909-%'")}
builtinCount=conn.execute('select count(*) from entries').fetchone()[0];conn.close()
check({f'pop909-{id}.json' for id in songs}==set(catalog),'live catalog coverage')
rawChecks=0
for id,x in songs.items():
    score=load(ROOT/f'Songs/pop909-{id}.json');entry=catalog[f'pop909-{id}.json'];speed=entry['options']['speed']
    one=[n for n in score['notes'] if n['track']==1 and not n['percussion']];two=[n for n in score['notes'] if n['track']==2 and not n['percussion']]
    s1=[(n['startMs']/speed,(n['startMs']+n['durationMs'])/speed) for n in one];s2=[(n['startMs']/speed,(n['startMs']+n['durationMs'])/speed) for n in two]
    duration=max(score['lengthMs'],max(n['startMs']+n['durationMs'] for n in score['notes']))/speed
    for key,spans in [('rawTrack1Sound',s1),('rawTrack12Sound',s1+s2)]:
        expected=rawgaps(spans,duration)
        for k,v in expected.items():check(near(v,x[key][k]),f'independent raw union {id}/{key}/{k}');rawChecks+=1
    overlap=intersection(s1,s2);check(near(overlap,x['rawTrackOverlap']['overlapMs']),f'independent overlap {id}');rawChecks+=1
    for instrument in instruments:
        row=bykey[id,instrument];check(row['passed'],'row failed')
        check(row['original']['onsets']['distinctOnsets']==len({n['startMs'] for n in one}),'original source-onset count')
        check(row['candidate']['onsets']['distinctOnsets']==len({n['startMs'] for n in one+two}),'candidate source-onset count')
        for key,tracks in [('originalOptions',[1]),('candidateOptions',[1,2])]:
            expected=entry['options'].copy();expected['instrumentId']=instrument;expected['tracks']=tracks
            check(row[key]==expected,'exact catalog options comparison')
        for key in ['original','candidate']:
            p=row[key];check(p['output']>0,'nonzero plan');g=p['sound']['gapsGe5s'];check(len(g)==p['sound']['countGe5s'],'sound gap count')
            check(near(sum(v['durationMs'] for v in g),p['sound']['totalGe5sMs']),'sound long total');check(p['sound']['maximumInternalMs']>=max([v['durationMs'] for v in g],default=0)-1e-6,'sound maximum')
            if instrument in ['windsong','floral','vintage','ukulele','euphonia']:check(p['sustainShortened']==0,'non-sustain clipping must be zero')
# Preserve the original reports; verify correction changed only sustainShortened (and added overlap schema).
for old in finalOld['matrix']:
    newrow=bykey[old['id'],old['instrument']]
    for key in ['original','candidate']:
        a=old[key].copy();b=newrow[key].copy();a.pop('sustainShortened');b.pop('sustainShortened');check(a==b,'non-sustain-stat change in rerun')
    check(old['delta']==newrow['delta'],'delta rerun changed')
check(len(matrix['disabledDrums'])==600,'600 drum rows');check(len({(x['id'],x['instrument'],tuple(x['tracks'])) for x in matrix['disabledDrums']})==600,'drum coverage')
check(all(x['output']==0 and x['passed'] for x in matrix['disabledDrums']),'all drum outputs zero')
check(len(focus['rows'])==18,'18 focus rows')
for f in focus['rows']:
    base=bykey[f['id'],f['instrument']];check(f['original']==base['original'] and f['candidate']==base['candidate'],'focus baseline reproduction')
    check(f['allTracks']['output']>0 and f['allTracks']['sound']['countGe5s']==0 and f['allTracks']['onsets']['countGe5s']==0,'all-tracks no >=5s internal sound/onset gaps')
    check(f['allTracksOptions']['tracks']==[1,2,3],'focused tracks')
for f in focusOld['rows']:
    current=next(x for x in focus['rows'] if x['id']==f['id'] and x['instrument']==f['instrument'])
    for key in ['original','candidate','allTracks']:
        a=f[key].copy();b=current[key].copy();a.pop('sustainShortened');b.pop('sustainShortened');check(a==b,'focus changed except clipping count')
check(changes['summary']['removedKeyOnsets']==sum(x['delta']['removedKeyOnsets'] for x in rows)==436,'436 classification count')
check(sum(x['removedKeyOnsets'] for x in changes['rows'])==436 and all(x['diagnosticCounterfactual']['removedOriginalKeyOnsets']==0 for x in changes['rows']),'native chord counterfactual')
check(all(d['cause']=='EXACT_NATIVE_CHORD_REPLACES_INDIVIDUAL_MELODY_KEY' for x in changes['rows'] for d in x['detail']),'436 native classes')
waveChecks=[]
for w in initial['waveEvidence']:
    p=pathlib.Path(w['path']);check(sha(p)==w['sha256'],'WAV sha')
    with wave.open(str(p),'rb') as wf:
        check(wf.getnchannels()==1 and wf.getsampwidth()==2 and wf.getframerate()==22050,'WAV format')
        ms=wf.getnframes()/wf.getframerate()*1000;check(ms<=30000+1000/22050 and near(ms,w['waveDurationMs']),'WAV duration');check(any(wf.readframes(wf.getnframes())),'WAV PCM nonzero')
    waveChecks.append({'path':str(p),'durationMs':ms,'sha256':w['sha256'],'played':False})
check(len(waveChecks)==8,'8 WAV fragments')
currentCore=TOOL/'core-tests/core-test-report.json';baselineCore=TOOL/'core-tests-baseline30/core-test-report.json'
current=load(currentCore);baseline=load(baselineCore);check((current['cases'],current['failures'])==(159,2),'live failure counts');check((baseline['cases'],baseline['failures'])==(159,0),'baseline pass counts')
manifest=load(TOOL/'baseline30-copy-manifest.json')
for item in manifest:check(sha(TOOL/'baseline30-repo/Songs'/item['name'])==item['sourceSha256']==item['copySha256'],'baseline fixture unchanged after tests')
migrationEvidence=[]
for prefix in ['core-tests','core-tests-baseline30']:
    for db in (TOOL/prefix).glob('fixtures/*/library-*/旧数据/library.db'):
        conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True);n=conn.execute('select count(*) from entries').fetchone()[0];retired=conn.execute('select count(*) from retired_legacy').fetchone()[0];marker=conn.execute("select value from meta where key='legacy_migrated'").fetchone();conn.close()
        builtins=builtinCount if prefix=='core-tests' else 30
        migrationEvidence.append({'run':prefix,'fixtureDatabase':str(db),'builtinCount':builtins,'personalEntryCount':n,'observedLibraryStoreCount':n+builtins,'expectedHardCodedCount':31,'retiredCount':retired,'backupCount':len(list(db.parent.glob('*.bak'))),'legacyMigratedMarker':marker})
check(len(migrationEvidence)==2 and {x['observedLibraryStoreCount'] for x in migrationEvidence}=={133,31},'31-vs-133 fixture issue established')

# Protection covers live source, all production project bin/obj, Songs/catalog and root documents, never real UserData.
before=load(TOOL/'protected-before.json');protected={};paths=[]
for name in ['QinBan.Core','QinBan.Tests','QinBan.Desktop','QinBan.LibraryTools','AutoMidiPlayer.Data','AutoMidiPlayer.WPF','Songs']:
    for base,ds,fs in os.walk(ROOT/name):
        ds[:]=[d for d in ds if d.lower()!='userdata']
        paths.extend(pathlib.Path(base)/f for f in fs)
paths+=list(ROOT.glob('*.*'))
for p in paths:
    if p.is_file():protected[str(p.relative_to(ROOT)).replace('\\','/')]= {'sha256':sha(p),'size':p.stat().st_size,'mtimeNs':p.stat().st_mtime_ns}
added=sorted(set(protected)-set(before));missing=sorted(set(before)-set(protected));content=[p for p in before if p in protected and before[p]['sha256']!=protected[p]['sha256']];timestamps=[p for p in before if p in protected and before[p]['mtimeNs']!=protected[p]['mtimeNs']]
check(not(added or missing or content or timestamps),'protected live production source/bin/obj/content/mtime drift')
productionArtifactCount=sum('/bin/' in p or '/obj/' in p for p in protected)

# Structured statistics and 900 CSV rows.
rawWeighted=sum(x['rawTrackOverlap']['overlapMs'] for x in songs.values())/sum(x['rawTrackOverlap']['track2ActiveMs'] for x in songs.values())
addedWeighted=sum(x['delta']['addedTrack2OverlapWithOriginalTrack1Ms'] for x in rows)/sum(x['delta']['addedTrack2ActiveMs'] for x in rows)
worse=[x for x in rows if x['candidate']['sound']['countGe5s']>x['original']['sound']['countGe5s']]
check(len(worse)==9 and {x['id'] for x in worse}=={'223'},'9 rows exactly 223')
counts=collections.Counter(x['id'] for x in changes['rows']);check(len(counts)==20,'20 changed songs')
perInstrument=[]
for instrument in instruments:
    group=[x for x in rows if x['instrument']==instrument]
    perInstrument.append({'instrument':instrument,'rows':len(group),'originalSoundGe5s':sum(x['original']['sound']['countGe5s'] for x in group),'candidateSoundGe5s':sum(x['candidate']['sound']['countGe5s'] for x in group),'originalOnsetGe5s':sum(x['original']['onsets']['countGe5s'] for x in group),'candidateOnsetGe5s':sum(x['candidate']['onsets']['countGe5s'] for x in group),'candidateMaxExactKeys':max(x['candidate']['density']['maxExactOnsetKeys'] for x in group),'candidateMaxConcurrentVoices':max(x['candidate']['density']['maxConcurrentVoices'] for x in group),'removedOriginalKeyOnsets':sum(x['delta']['removedKeyOnsets'] for x in group)})
flat=[]
for x in rows:
    a,b=x['original'],x['candidate'];flat.append({'id':x['id'],'title':x['title'],'instrument':x['instrument'],'speed':x['originalOptions']['speed'],'transpose':x['originalOptions']['transpose'],
        'originalOutput':a['output'],'candidateOutput':b['output'],'soundGe5sOriginal':a['sound']['countGe5s'],'soundGe5sCandidate':b['sound']['countGe5s'],'maxSoundGapOriginalMs':a['sound']['maximumInternalMs'],'maxSoundGapCandidateMs':b['sound']['maximumInternalMs'],
        'onsetGe5sOriginal':a['onsets']['countGe5s'],'onsetGe5sCandidate':b['onsets']['countGe5s'],'firstOriginalMs':a['onsets']['firstOnsetMs'],'firstCandidateMs':b['onsets']['firstOnsetMs'],'leadingCandidateMs':b['sound']['leadingMs'],'trailingCandidateMs':b['sound']['trailingMs'],
        'rawTrack2OverlapRatio':x['rawTrackOverlap']['ratioOfTrack2'],'addedEmittedTrack2OverlapRatio':x['delta']['addedTrack2SoundOverlapRatio'],'candidateMaxExactKeys':b['density']['maxExactOnsetKeys'],'candidateMaxConcurrentVoices':b['density']['maxConcurrentVoices'],
        'removedOriginalKeyOnsets':x['delta']['removedKeyOnsets'],'changedCommonKeyOnsets':x['delta']['changedCommonKeyOnsets'],'retention':x['delta']['originalKeyOnsetRetention'],'sustainShortenedOriginal':a['sustainShortened'],'sustainShortenedCandidate':b['sustainShortened']})
csvnew('mapping-matrix-900.csv',flat)
focusedFlat=[]
for x in focus['rows']:
    p=x['allTracks'];focusedFlat.append({'id':x['id'],'title':x['title'],'instrument':x['instrument'],'output':p['output'],'firstOnsetMs':p['onsets']['firstOnsetMs'],'soundGe5s':p['sound']['countGe5s'],'maxSoundGapMs':p['sound']['maximumInternalMs'],'onsetGe5s':p['onsets']['countGe5s'],'maxOnsetGapMs':p['onsets']['maximumGapMs'],'maxExactKeys':p['density']['maxExactOnsetKeys'],'maxConcurrentVoices':p['density']['maxConcurrentVoices'],'melodyKeyOnsetRetention':x['melodyKeyOnsetRetention']['originalKeyOnsetRetention'],'removedMelodyKeyOnsets':x['melodyKeyOnsetRetention']['removedKeyOnsets'],'changedCommonKeyOnsets':x['melodyKeyOnsetRetention']['changedCommonKeyOnsets'],'sustainShortened':p['sustainShortened'],'nativeChords':p['report']['nativeChords'],'simplified':p['report']['simplified']})
csvnew('mapping-focused-alltracks-18.csv',focusedFlat)
dump('mapping-gap-count-increase.json',{'rows':worse,'reason':'223: both candidate head gaps lie before original first onset, tail gap lies after original last sound end. Earlier/later notes reclassify former leading/trailing silence as internal gaps. Original 33.362s internal gap shrinks below5s throughout, does not lengthen.','lossless':False})
dump('mapping-core-fixture-rerun.json',{'current132':{'reportPath':str(currentCore),'cases':current['cases'],'assertions':current['assertions'],'failures':[x for x in current['results'] if x['status']=='FAIL']},'baseline30':{'reportPath':str(baselineCore),'cases':baseline['cases'],'assertions':baseline['assertions'],'failures':baseline['failures'],'allPassed':True},'sameUnmodifiedTestsAssemblySha256':sha(TOOL/'artifacts/bin/QinBan.Tests/release/QinBan.Tests.dll'),'sourceHardCodes':['QinBan.Tests/Program.cs:114 files.Length==30','QinBan.Tests/LibraryTests.cs:115 store.Count==31'],'migrationEvidence':migrationEvidence,'baselineCopyManifest':str(TOOL/'baseline30-copy-manifest.json'),'conclusion':'Both observed failures are mismatched old30 fixtures, not reproduced as new Core bugs on correct unchanged old30 fixture. No claim of complete production/game validation.'})
summary={'matrix':matrix['summary'],'perInstrument':perInstrument,'rawTrack2TimeWeightedOverlap':rawWeighted,'rawTrack2MedianPerSongOverlap':statistics.median(x['rawTrackOverlap']['ratioOfTrack2'] for x in songs.values()),'addedEmittedTrack2TimeWeightedOverlap':addedWeighted,'rawSongsOver50PercentOverlap':sum(x['rawTrackOverlap']['ratioOfTrack2']>.5 for x in songs.values()),'rawSongsOver80PercentOverlap':sum(x['rawTrackOverlap']['ratioOfTrack2']>.8 for x in songs.values()),'soundGe5sTotalWorsenedRows':sum(x['candidate']['sound']['totalGe5sMs']>x['original']['sound']['totalGe5sMs']+1e-6 for x in rows),'affectedNativeChordSongs':20,'affectedNativeChordRows':40,'focusedAllTracks':focus['summary']}
dump('mapping-summary.json',summary)

def seconds(x):return f'{x/1000:.3f}'
def percent(x):return f'{x*100:.2f}%'
lines=['# POP100 静音诊断与只读映射验证（2026-10-06）','',
'## 结论与当下手动建议','',
'- 本次不改生产、不改运行安装、不改真实 UserData；只新增 probe 及 mapping-* 诊断文件。',
'- **不建议将 100 首统一默认 1+2 表述为无损修复。** 连续性显著改善，但大约一半的轨2活跃时段与轨1重叠，吉他原生和弦会替换主旋律单键、同键延音也会截短。',
'- **035《七里香》：手动 1+2 仍不够。** 所有9乐器均仍有 121.345010–136.690073 秒（15.345063秒）内部 SoundMs 空白；首音14.524641秒。若目标是减少空白并保留前奏，可手动选1+2+3：18个重点计划中035的9个计划均无>=5秒内部静音/起音gap，首音0.580986秒；这不是全轨音乐精校。',
'- **038《三寸日光》：手动1+2已足够解决本次>=5秒内部空白。** 9个乐器均达到该条件，首音0.343750秒；不必为这个目标额外加轨3。',
'- 全轨重点计划仍非无损。035吉他原主旋律key-onset保留87.38%（各替换51）；038为75.94%（各替换83）。windsong/harmonic保留键位与起音100%不等于音长/力度/来源完全不变。','',
'## 构建与安全范围','',
'- 直接 ProjectReference 现有 QinBan.Core，调用公共 GameMapping.Build；没有复制音高折叠/半音/和弦选择 mapper。',
'- 使用 ../.tools/dotnet/dotnet.exe 与现有缓存的本地nupkg；唯一restore源为probe内 offline-feed，无网络fallback。CLI home、NuGet、TEMP、Core/Tests bin/obj 全部重定向到 tools/Pop100GapProbe。',
'- 核验生产保护集合：'+str(len(protected))+'个文件，其中生产 bin/obj 文件'+str(productionArtifactCount)+'个；前后 SHA256/文件集合/mtime 全一致。真实 UserData 不读取，不用其哈希来证明安全。',
'- WAV临时文件先在probe的wave-staging生成，再仅复制mapping-*.wav到诊断目录；没有播放、没有PlaybackEngine、没有OS输入。Core测试中的UserData/旧数据是本工具内自建夹具，不是真实目录。','',
'## 测量定义与断言','',
'- SoundMs 静音：对半开区间 [StartMs,StartMs+SoundMs) 做并集，统计相邻活跃段之间>=5000ms空档；首尾休止单列。不是按相邻音符EndMs简单相减。',
'- 起音gap：相邻不同StartMs之差，>=5000ms；即使前音延音覆盖gap也统计，所以不是听感静音。',
'- overlap：轨2与轨1各自活跃区间并集的交集时长/轨2活跃时长。另提供新增且仍归属于轨2的映射音与原轨1计划的SoundMs交叠比；原生和弦及去重后来源归属不等于声部拆解。',
'- 密度同时提供精确同起音的键/和弦展开声部数，以及SoundMs并发键/声部峰值；最大和弦5不代表整段最多5个声音。',
'- 1800个旋律计划非空；所有起音等于所选源轨绝对起音/实际速度，Track/Velocity有同起音源证据；原生和弦音级来自现存同拍音组，允许合并但不发明伴奏。',
'- 时序不压缩；源尾休止和总时长保持；每首真实移调/速度/Octave保留，除了跨乐器InstrumentId和候选Tracks之外所有Options逐字段相同；源notes和整个SongDocument内存序列、源谱与catalog文件哈希不变。',
'- SustainShortened校正为支持延音且实际触及同键重触发释放上限的音数；不把不同音长的同拍身份候选或原生和弦最短时长误算为sustain截短。','',
'## 900矩阵覆盖与统计','',
'100首真实catalog POP909×9乐器=900行；每行原[1]与候选[1,2]两计划，共1800旋律计划；100×3鼓×2选择=600空计划；每轮实际2400次GameMapping.Build。最终900/900通过、'+f"{matrix['summary']['assertions']:,}"+'断言。','',
'| 指标（跨乐器行求和，不是独立歌曲数） | [1] | [1,2] |','|---|---:|---:|',
'| >=5秒内部SoundMs空档数 | 1,143 | 112 |','| 存在上述空档的矩阵行 | 783 | 85 |',
'| 上述空档合计秒 | '+seconds(matrix['summary']['soundInternalGe5sOriginalMs'])+' | '+seconds(matrix['summary']['soundInternalGe5sCandidateMs'])+' |',
'| >=5秒起音gap数 | 1,674 | 477 |','| 起音gap合计秒 | '+seconds(matrix['summary']['onsetGe5sOriginalMs'])+' | '+seconds(matrix['summary']['onsetGe5sCandidateMs'])+' |','',
'内部长空档数量改善725行、相同166行、增加9行；长空档总时长增加0行。精确同起音候选最大5键/5声部，SoundMs并发峰值10键/10声部。原不同起音时刻删除0；原key-onset删除436，共同key-onset属性改变7,931。','',
'| 乐器 | 行 | SoundMs长空档 原→候选 | 起音长gap 原→候选 | 候选精确最大键 | 候选并发峰值声部 | 原key-onset替换 |','|---|---:|---:|---:|---:|---:|---:|']
for x in perInstrument:lines.append(f"| {x['instrument']} | {x['rows']} | {x['originalSoundGe5s']}→{x['candidateSoundGe5s']} | {x['originalOnsetGe5s']}→{x['candidateOnsetGe5s']} | {x['candidateMaxExactKeys']} | {x['candidateMaxConcurrentVoices']} | {x['removedOriginalKeyOnsets']} |")
lines+=['','100首去重后的轨2时长加权overlap='+percent(rawWeighted)+'，逐首中位数='+percent(summary['rawTrack2MedianPerSongOverlap'])+'，范围0–99.52%；50首超过50%、2首超过80%。新增仍归属轨2的映射音按时长加权overlap='+percent(addedWeighted)+'（跨900行）；不能称仅填休止。','',
'## 035/038 原[1]与[1,2]重点','',
'| 曲 | 乐器 | 输出 原→候选 | 最大内部SoundMs空档 秒 原→候选 | 首音 秒 原→候选 | 原key-onset保留率 | 原轨2overlap | 新映射轨2overlap |','|---|---|---:|---:|---:|---:|---:|---:|']
for x in rows:
    if x['id'] in ['035','038'] and x['instrument'] in ['windsong','harmonic']:
        a,b=x['original'],x['candidate'];lines.append(f"| {x['id']} {x['title']} | {x['instrument']} | {a['output']}→{b['output']} | {seconds(a['sound']['maximumInternalMs'])}→{seconds(b['sound']['maximumInternalMs'])} | {seconds(a['onsets']['firstOnsetMs'])}→{seconds(b['onsets']['firstOnsetMs'])} | {percent(x['delta']['originalKeyOnsetRetention'])} | {percent(x['rawTrackOverlap']['ratioOfTrack2'])} | {percent(x['delta']['addedTrack2SoundOverlapRatio'])} |")
lines+=['','035 [1]内部空档120.528109–149.313306秒；[1,2]缩为121.345010–136.690073秒。038 [1]内部空档133.748438–148.843750秒及214.165625–220.843750秒，[1,2]均消除。首尾休止不算在上述空档数量中，详见JSON/CSV。','',
'## 18个重点[1,2,3]计划','',
'仅2首×9乐器；共18全轨计划，另重算36个[1]/[1,2]基线用于独立一致性断言，全部通过。所有计划内部SoundMs空档和起音gap均无>=5秒；035首音0.580986秒，038首音0.343750秒。','',
'| 曲 | 乐器 | 输出 | 最大内部SoundMs空档 秒 | 精确键/并发声部峰值 | 原主旋律key-onset保留 | 同键sustain截短音数 | 原生和弦/和弦限额省略音数 |','|---|---|---:|---:|---:|---:|---:|---:|']
for x in focusedFlat:lines.append(f"| {x['id']} | {x['instrument']} | {x['output']} | {seconds(x['maxSoundGapMs'])} | {x['maxExactKeys']}/{x['maxConcurrentVoices']} | {percent(x['melodyKeyOnsetRetention'])} | {x['sustainShortened']} | {x['nativeChords']}/{x['simplified']} |")
lines+=['','035全轨最大起音gap1.632041秒，038为3秒；windsong/harmonic精确同拍峰值5键，035并发8/7声部、038并发10/9声部。保留率按原映射(key,StartMs)计算，不代表原源音高逐个保留。','',
'## 9个候选长gap计数增加行：223《半城烟沙》','',
'涉及 '+', '.join(instruments)+'，共9行。原内部长空档133.189557–166.551602秒，33.362045秒。候选将其中有效SoundMs覆盖30.457951秒，剩余空白总共2.904094秒，原>=5秒中段空档消失。',
'候选3个>=5秒内部空档：15.905161–24.568947（8.663786秒）、26.409463–34.137906（7.728443秒）、263.551531–273.879110（10.327579秒）。前两个落在原首音34.137906秒之前，后一个落在原末次SoundMs结束263.551531秒之后；新前后段使原首尾静音被重新分类为内部。计数1→3，最大33.362→10.328秒、总33.362→26.720秒。不能单凭gap数量增加称时序被压坏，也不能称1+2无损。','',
'## 436个原key-onset被替换：20首×两种吉他','',
'全部涉及ukulele/euphonia，各218个，共40矩阵行。逐音证据确认候选在同一起音生成现有音级匹配的原生和弦键，替换原主旋律单键；新增起音仍来自真实源轨，原生和弦使用原同拍组最短时长。40行诊断副本仅关闭NativeGuitarChords后，真实GameMapping.Build均保留原key-onset，支持该归因；这不是建议修改生产设置。','',
'| ID | 曲名 | ukulele替换数 | euphonia替换数 | 合计 |','|---|---|---:|---:|---:|']
changeSongs=collections.defaultdict(dict)
for x in changes['rows']:changeSongs[x['id']][x['instrument']]=x
for id,group in sorted(changeSongs.items()):
    a,b=group['ukulele'],group['euphonia'];lines.append(f"| {id} | {a['title']} | {a['removedKeyOnsets']} | {b['removedKeyOnsets']} | {a['removedKeyOnsets']+b['removedKeyOnsets']} |")
lines+=['','另有共同key-onset属性变化（力度/来源轨/音长/Hold/同键延音释放），详见delta；既有映射音并非逐条原样保留。这与原始notes和文件字节不变是两个证据层次。','',
'## Core 157/159失败及正确fixture复跑','',
'- 同一未修改Tests DLL在当前132首Songs下：157/159，通过3882断言，2失败。',
'- 失败1：Program.cs:114硬编码files.Length==30，当前132个JSON，报expected 30 built-ins。',
'- 失败2：LibraryTests.cs:115硬编码迁移后store.Count==31（30内置+1个人）。现场测试自建数据库有1个个人条目、1个retired、1个backup、legacy_migrated标记；CountAll实际将132内置+1个人计为133。失败不是备份缺失。',
'- 将用户指定source-snapshot/Songs原30文件及catalog原样复制到tools/Pop100GapProbe/baseline30-repo/Songs；未改任何测试、未裁剪当前生产Songs。参数1为工具内输出目录、参数2为该隔离repo，测试自动创建独立fixtures/<GUID>。',
'- 原30 fixture复跑：**159/159，3978断言，0失败**。迁移观察数=30+1=31；源baseline复制文件hash前后不变。因而本次两个失败被确认是旧30/31数量假设与当前曲库不匹配，未在正确fixture复现为新Core bug。不是32首要求。当前132环境仍157/159，不能删去这次失败或称现有整套测试全绿。','',
'## 验证、失败记录与测试边界','',
'- 最终离线构建0警告0错误，probe自测136断言通过（包括非sustain不得误计、实际同键sustain截短回归）；独立Python重算原轨区间并集/overlap、校验全部Options/矩阵/鼓覆盖、重点基线再现、8份PCM/WAV时长/哈希以及保护快照通过。',
'- 8份WAV为035/038×windsong/harmonic×[1]/[1,2]同窗口对比，每份30秒（含450ms释放），PCM非零，未播放。切片边界已有音会裁剪再起音，不是完整声音状态/原唱/游戏采样。未生成全轨WAV，未开启任何音频播放。',
'- 首次构建有一个nullable警告，已在probe内修正；初次工具检索正则及一次临时统计字段读取失败均已改用正确命令完成，未把失败结果用于结论。',
'- probe旧版sustainShortened包含非sustain不同音长身份的误计；已修正并增加回归，自测136通过。既有mapping-results.json、mapping-results-final.json、mapping-focused-alltracks.json保留不覆盖；除该字段外静音/起音/密度/retention重算一致。以mapping-results-verified.json与mapping-focused-alltracks-verified.json为校正指标权威版本。',
'- 本次是现有Core映射与合成片段验证，**不是音乐人工审校、真实原神输入/声音、WPF交互渲染、安装冷启动或现场演奏验证**。未跑WPF/真实游戏/安装验证，因任务禁止生产输入和改动。原始MIDI/tempo源审计由上游任务另行负责，本probe不替代该审计。','',
'## 主要产物（绝对路径）','']
for name in ['mapping-results-verified.json','mapping-matrix-900.csv','mapping-summary.json','mapping-focused-alltracks.json','mapping-focused-alltracks-verified.json','mapping-focused-alltracks-18.csv','mapping-key-onset-changes.json','mapping-gap-count-increase.json','mapping-core-fixture-rerun.json','mapping-validation.json']:
    lines.append('- `'+str(OUT/name)+'`')
lines+=['','### 可复跑命令（新的输出名，拒绝覆盖已有报告）','','```powershell',f"& '{TOOL/'Build-Probe.ps1'}' -IncludeCoreTests",f"& '{ROOT.parent/'.tools/dotnet/dotnet.exe'}' '{TOOL/'artifacts/bin/Pop100GapProbe/release/Pop100GapProbe.dll'}' --self-test",f"& '{ROOT.parent/'.tools/dotnet/dotnet.exe'}' '{TOOL/'artifacts/bin/Pop100GapProbe/release/Pop100GapProbe.dll'}' '{ROOT}' '{OUT/'mapping-results-new-run.json'}'",f"& '{ROOT.parent/'.tools/dotnet/dotnet.exe'}' '{TOOL/'artifacts/bin/Pop100GapProbe/release/Pop100GapProbe.dll'}' --focused-alltracks '{ROOT}' '{OUT/'mapping-focused-new-run.json'}'",f"& '{ROOT.parent/'.tools/dotnet/dotnet.exe'}' '{TOOL/'artifacts/bin/QinBan.Tests/release/QinBan.Tests.dll'}' '{TOOL/'core-tests-baseline30-new-run'}' '{TOOL/'baseline30-repo'}'",'```','']
new('mapping-report.md','\n'.join(lines))
artifactManifest=[{'path':str(p),'sha256':sha(p),'size':p.stat().st_size} for p in sorted(OUT.glob('mapping-*')) if p.is_file()]
dump('mapping-validation.json',{'status':'PASS_MATRIX_FOCUS_PCM_PROTECTION_AND_OLD30_FIXTURE__LIVE132_CORE_TESTS_2_EXPECTED_FIXTURE_FAILURES_RETAINED','independentChecks':checks,'independentRawStatChecks':rawChecks,'protection':{'files':len(protected),'productionBinObjFiles':productionArtifactCount,'added':added,'missing':missing,'hashChanged':content,'mtimeChanged':timestamps,'snapshotPath':str(TOOL/'protected-before.json'),'userDataRead':False},'selfTestAssertions':136,'correctedStats':['sustainShortened'],'preservedSupersededReports':['mapping-results.json','mapping-results-final.json','mapping-focused-alltracks.json'],'waveEvidence':waveChecks,'artifacts':artifactManifest})
print(json.dumps({'independentChecks':checks,'protectedFiles':len(protected),'productionBinObjFiles':productionArtifactCount,'rawWeightedOverlap':rawWeighted,'addedEmittedWeightedOverlap':addedWeighted,'report':str(OUT/'mapping-report.md')},ensure_ascii=False,indent=2))
