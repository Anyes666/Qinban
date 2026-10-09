from pathlib import Path
import collections, datetime, hashlib, json, wave

TOOL=Path(__file__).resolve().parent
REPO=TOOL.parents[1]
OUT=REPO/'.validation/smart-interludes-2026-10-06'
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def save(name,value):
 p=OUT/name
 if p.parent!=OUT or not p.name.startswith('matrix-'):raise RuntimeError('Output outside write set')
 with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
 return p
def save_text(p,text):
 with p.open('x',encoding='utf-8') as f:f.write(text)
def union(notes):
 result=[]
 for a,b in sorted((n['startMs'],n['startMs']+n['durationMs']) for n in notes):
  if result and a<=result[-1][1]:result[-1][1]=max(result[-1][1],b)
  else:result.append([a,b])
 return result

m=load(OUT/'matrix-final.json'); slots=load(OUT/'matrix-final-slots.json'); ev=load(OUT/'matrix-final-evidence.json'); fx=load(OUT/'matrix-final-fixtures.json')
rows=[r for r in m['rows'] if r['instrument']=='windsong']
r=next(r for r in rows if r['id']=='592')
p=next(s for s in slots if s['caseName']=='catalog-tracks1/592/windsong')
source=load(REPO/'Songs/pop909-592.json'); notes=source['notes']
g=next(s for s in r['on']['allNoteOffRestsGe5s'] if s['startMs']>0 and s['endMs']<r['on']['durationMs'])
start,end=g['startMs'],g['endMs']
full=[n for n in notes if n['track']!=1 and not n.get('percussion',False) and n['startMs']>=start and n['startMs']+n['durationMs']<=end]
overlap=[n for n in notes if n['track']!=1 and not n.get('percussion',False) and n['startMs']<start<n['startMs']+n['durationMs']]
all_active=union([n for n in notes if not n.get('percussion',False)])
true_rest=next({'startMs':a[1],'endMs':b[0],'durationMs':b[0]-a[1]} for a,b in zip(all_active,all_active[1:]) if a[1]>=start and b[0]==end)
last=next(n for n in p['actualAddedRawNotes'] if abs(n['startMs']+n['durationMs']-start)<1e-6)
analysis={
 'status':'RETAINED_SAFE_GREEDY_REST_NOT_FORCED_FILLED','song':'592','sourceFile':str(REPO/'Songs/pop909-592.json'),'sourceSha256':sha(REPO/'Songs/pop909-592.json'),
 'originalSelectedRawRest':next(s for s in p['rawEligibleRests'] if s['startMs']<=start and end<=s['endMs']),
 'safeSlot':next(s for s in p['safeSlots'] if s['startMs']<=start and end<=s['endMs']),
 'remainingMappedAndRawNoteOffRest':g,'nextSelectedSourceOnsetMs':end,'lastGreedyBridgeNote':last,
 'completeUnselectedNonDrumNotesFittingRemainingRest':len(full),'sourceNotesAlreadyStartedBeforeRestButSoundingIntoIt':overlap,
 'trueAllNonDrumSourceSilence':true_rest,'greedyBoundaryUnavailablePrefixMs':true_rest['startMs']-start,
 'classification':'Mixed: greedy monophonic whole-note selection leaves 1709.089ms of earlier-onset source tails unavailable, followed by 3810.111ms true all-source silence. No full unselected source note starts and ends inside the residual 5519.200ms interval.',
 'reason':'Bridge pitch75 at165676.021ms is chosen whole and lasts to166385.111ms. Later bridge pitch67 starts166248.747ms before this ends and is rejected for overlap. Piano notes start165948.748ms, also overlap the already chosen bridge, and cannot be re-attacked/clipped at166385.111ms. Latest original piano note-off is168094.200ms. Every non-drum source track is then silent until selected track1 resumes171904.311ms. Not an 8ms padding problem, not missing source mutation, and not a requirement to invent/retime/truncate notes.',
 'changesPerformed':0,'playbackReRun':False,'audioReRun':False,'sourceOrDeploymentWrites':0,
 'windsongAggregate':{'songsWithInternalNoteOffRestGe5sOff':sum(x['off']['internalNoteOffGapsGe5s']>0 for x in rows),'songsWithInternalNoteOffRestGe5sOn':sum(x['on']['internalNoteOffGapsGe5s']>0 for x in rows),
  'internalNoteOffRestSegmentsGe5sOff':sum(x['off']['internalNoteOffGapsGe5s'] for x in rows),'internalNoteOffRestSegmentsGe5sOn':sum(x['on']['internalNoteOffGapsGe5s'] for x in rows),
  'internalOnsetGapsGe5sOff':sum(x['off']['internalOnsetGapsGe5s'] for x in rows),'internalOnsetGapsGe5sOn':sum(x['on']['internalOnsetGapsGe5s'] for x in rows),'onsetGapBoundary':'An onset gap can contain a long held note and is not equivalent to silence.'}}
assert len(full)==0 and len(overlap)==5 and abs(end-start-5519.2)<1e-6
save('matrix-final-592-rest-analysis.json',analysis)

boot=load(TOOL/'bootstrap-protected-before.json')
def file_check(old):
 path=Path(old['path']);exists=path.is_file();after=sha(path) if exists else None
 return {'path':str(path),'sha256Before':old['sha256'].lower(),'sha256After':after,'unchanged':exists and old['sha256'].lower()==after}
song_checks=[file_check(x) for x in boot['songFiles']]
# Explicit 140-file subset, not an expectation of 140 catalog entries:
# 132 immutable score JSON files + catalog.db + seven unchanged Core input files.
seven={'PlaybackEngine.cs','PreviewAudio.cs','SongParser.cs','InstrumentCatalog.cs','ScorePlaybackPolicy.cs','ScorePreparer.cs','QinBan.Core.csproj'}
core_seven=[file_check(x) for x in boot['coreSource'] if Path(x['path']).name in seven]
protected140=song_checks+core_seven
assert len(protected140)==140 and all(x['unchanged'] for x in protected140)
raw_notes=[]
for x in song_checks:
 path=Path(x['path'])
 if path.suffix.lower()=='.json':
  data=load(path);n=data['notes'];text=json.dumps(n,ensure_ascii=False,separators=(',',':'))
  raw_notes.append({'path':str(path),'rawNotes':len(n),'rawNotesSha256Now':hashlib.sha256(text.encode('utf-8')).hexdigest(),'unchangedByIdenticalBeforeAfterFileSha256':x['unchanged']})
final_core=load(TOOL/'final-core-source-before.json'); core_final_checks=[file_check(x) for x in final_core]
assert all(x['unchanged'] for x in core_final_checks)

old=load(TOOL/'protected-before.json'); expanded=[file_check(x) for x in old['files']]
changed=[x for x in expanded if not x['unchanged']]
def select(fragment):return [x for x in expanded if fragment.lower() in x['path'].lower()]
old_probes=[x for x in expanded if any('\\tools\\'+name+'\\' in x['path'].lower() for name in ['pop100gapprobe','pop100recorder','pop100tool'])]
old_evidence=[x for x in expanded if '\\.validation\\pop100-' in x['path'].lower()]
source_intake=select('\\catalog-intake\\pop100-2026-10-06\\')
userdata=select('\\userdata\\')
for label,data in [('oldProbes',old_probes),('oldEvidence',old_evidence),('sourceIntake',source_intake),('realUserData',userdata)]:
 print(label,len(data),'unchanged',sum(x['unchanged'] for x in data))
integrity={
 'status':'PASS_140_IMMUTABLE_INPUTS_AND_FINAL_CORE_PIN','protectedInputSubsetFileCount':len(protected140),'protectedInputSubsetUnchanged':sum(x['unchanged'] for x in protected140),
 'protected140Definition':'132 Songs/*.json + Songs/catalog.db + Core PlaybackEngine.cs, PreviewAudio.cs, SongParser.cs, InstrumentCatalog.cs, ScorePlaybackPolicy.cs, ScorePreparer.cs, QinBan.Core.csproj. Explicit sidecar subset; 140 is file hash count, not catalog entry count.',
 'catalogEntries':m['summary']['catalogEntries'],'scoreJsonFiles':len(raw_notes),'catalogSha256':sha(REPO/'Songs/catalog.db'),
 'sourceNoteFileHashesUnchanged':all(x['unchanged'] for x in song_checks),'rawNoteCountAll132':sum(x['rawNotes'] for x in raw_notes),
 'protected140':protected140,'rawNoteFingerprintsAll132':raw_notes,
 'finalCoreSourcePinnedUnchanged':all(x['unchanged'] for x in core_final_checks),'finalCoreSourcePin':core_final_checks,
 'finalCoreAssemblySha256':sha(TOOL/'artifacts/bin/SmartInterludeProbe/release/QinBan.Core.dll'),
 'expandedPriorSnapshotFiles':len(expanded),'expandedPriorSnapshotUnchanged':sum(x['unchanged'] for x in expanded),'observedChangedOutsideSidecar':changed,
 'expandedProtectedGroups':{label:{'files':len(data),'unchanged':sum(x['unchanged'] for x in data),'changed':len(data)-sum(x['unchanged'] for x in data)} for label,data in [('oldProbes',old_probes),('oldEvidence',old_evidence),('sourceIntake',source_intake),('realUserData',userdata)]},
 'concurrentParentBoundary':'Production bin/obj are being built by parent Main; expanded before/after differences are observations, not attributed to sidecar. This sidecar only issued writes under tools/SmartInterludeProbe and direct matrix-* evidence paths. No process stop, deploy, UserData write, commit, publish or upload.',
 'coreBootstrapToFinalParentChanges':[file_check(x) for x in boot['coreSource'] if not file_check(x)['unchanged']]}
save('matrix-final-integrity.json',integrity)

legacy=load(TOOL/'core-tests-final/core-test-report.json')
summary={
 'status':'PASS_REQUESTED_SIDECAR_VALIDATION','matrix':m['summary'],'ruleFixtures':fx['summary'],'audioAndRecording':ev['summary'],
 'protectedInputFiles':140,'protectedInputFilesUnchanged':140,'catalogEntries':132,'scoreJsonFiles':132,
 'oldSelectedReleaseChanges':{'oldChanges':12,'oldPairedCombinations':11,'oldShorteningRangeMs':[3.967,8.0],'finalMatrixChanges':0,'finalExtraChanges':0,'oldDetailsFile':str(OUT/'matrix-02-selected-release-details.json')},
 'remaining592Rest':analysis,'finalFailureAssertions':m['summary']['failureAssertions']+fx['summary']['failureAssertions']+ev['summary']['failureAssertions'],
 'finalAssertions':m['summary']['assertions']+fx['summary']['assertions']+ev['summary']['assertions'],
 'historicalFailuresNotHidden':{
  'bootstrapBuild':'First copied script used a non-BOM UTF8 Chinese default path under legacy PowerShell and failed command resolution. Only the new script default was changed to derive the SDK path; subsequent builds passed.',
  'matrix01':'957 oracle mismatch assertions from 891 primary pairs and 66 extras: canonical expected notes were inadvertently re-filtered by Tracks=[1]. Sidecar oracle was corrected to map its independently selected canonical notes with Tracks=null and smart=false. Original failures/diagnostic are preserved; matrix-02 and final have zero failures.',
  'intermediateCoreSuite':{'cases':legacy['cases'],'passed':legacy['cases']-legacy['failures'],'failures':legacy['failures'],'assertions':legacy['assertions'],'failedCases':[x for x in legacy['results'] if x['status']=='FAIL'],
    'boundary':'Intermediate direct suite against live132, not final parent191 suite: two legacy30 catalog/migration assumptions; two old no-padding boundary/piano fixtures. Parent changed SmartInterludeTests.cs six seconds after this DLL compilation and subsequently reported191/191. Logs retained, not rewritten or claimed passed by sidecar; no further suite/matrix expansion after user stop instruction.'},
  'oldCountReportingMisunderstanding':'Old matrix-01/02 requestedCatalogN140Observed was a report-only mistake. n140 means protected file hashes;132 catalog entries are correct. Removed from current report, old evidence is preserved.'},
 'parentReportedNotIndependentlyRetested':{'coreCases':'191/191','smartUiCases':14,'baselineCases':68,'auditionUiCases':39,'coldStartCatalogEntries':132,'attribution':'User/parent report in this chat, not sidecar UI/deploy execution.'},
 'remainingBoundaries':['884 added sustain planned SoundMs reductions from existing same-key release across900 pairs; raw added notes retain full source object identities and durations, selected holds/sounds all unchanged. Not a claim that every mapped added endpoint is unchanged.',
  'Software synthesized PCM only; no listening/game sample/acoustic fidelity certification. RecordingSink4x compressed smoke, not original-speed music timing evidence/full-song input.',
  'No UI/deploy/UserData changes. Parent handles closing PID17332 and in-place replacement.'],
 'files':{'report':str(OUT/'matrix-final-report.md'),'matrix':str(OUT/'matrix-final.json'),'csv':str(OUT/'matrix-final.csv'),'slots':str(OUT/'matrix-final-slots.json'),'typical':str(OUT/'matrix-final-typical.json'),'fixtures':str(OUT/'matrix-final-fixtures.json'),'evidence':str(OUT/'matrix-final-evidence.json'),'592':str(OUT/'matrix-final-592-rest-analysis.json'),'integrity':str(OUT/'matrix-final-integrity.json')}}
save('matrix-final-summary.json',summary)

report=f'''# 智能衔接100首 sidecar 最终验证 — 2026-10-06

## 结论与隔离范围

**本 sidecar 请求范围最终验证通过，失败断言 0；总断言 {summary['finalAssertions']:,}。** 不等于游戏音质/音乐审美或真实输入认证。仅新建/修改 `D:\\原神弹琴脚本\\AutoMidiPlayer\\tools\\SmartInterludeProbe\\*` 和本目录直接 `matrix-*` 文件。没有修改生产源码、旧 probe/旧证据/源谱/生产 bin/obj/真实 UserData，没有停止 PID17332 或部署/提交/发布/上传。父 Main 的源代码修订和并行构建不归 sidecar 写入。

最终本地 Core DLL SHA256：`{m['summary']['coreAssemblySha256']}`。源代码构建前后锁定一致。复用旧离线 Build 脚本的**新副本**，所有引用项目 bin/obj、NuGet feed/cache、CLI home、temp 都在 sidecar。

## 确切计数

| 检查 | 完成 | 最终失败 |
|---|---:|---:|
| 100首 × 9乐器显式关/开对照 | 900对 / 1,800 Build | 0 |
| 主矩阵旧选轨 legacy null => POP909 自动开启 | 900次 | 0 |
| extra：2x/0.5x、用户[1,2]、voice/guitar移调/八度 | 66对（36+18+12） | 0 |
| 三鼓安全 | 300组合 × false/true/null =900阻断 Build | 0 |
| public Build 主对照＋独立 raw-slot 补充检视 | 966组完整源身份/slot证明 | 0 |
| 内存规则夹具 | 38对＋4直接检查，包含2吉他×7原生和弦=14 | 0 |
| PlaybackEngine / RecordingSink | 18，累计72按下、held最终均0 | 0 |
| PreviewAudio PCM软件合成 | 8 WAV，各30.000秒 | 0 |
| 明确保护输入文件子集 | 140/140 哈希不变 | 0 |

主矩阵断言33,316；独立夹具1,310；音频/记录711。主矩阵原基底 key-onsets `{m['summary']['selectedOriginalKeyOnsets']:,}/{m['summary']['selectedOriginalKeyOnsets']:,}` 保留；extra `{m['summary']['extraSelectedKeyOnsets']:,}/{m['summary']['extraSelectedKeyOnsets']:,}` 保留。主矩阵和 extra 的基底 HoldMs / SoundMs 变化均为0，NativeChord变化0。真实POP909选轨[1]没有可计的原生和弦（0）；原生和弦保护实际由14个明确三/四音和弦夹具补足，不能把0误称为已覆盖大量原生和弦。

三秒资格始终由原始 selected note-off 区间并集确定；只在资格成立后，与包含 physical hold、arpeggio spread 和8ms*Speed释放尾垫的 free window求交。独立 oracle 实质更新了 slot 计算，不重新要求收窄 slot>=3s。实际 raw arrangement 只读检视确认每个新增对象都是未选、非鼓、完整原始 NoteEvent 引用；起止/pitch/velocity/track未改、一 onset一音、不重叠、不越 slot、不侵入基底占用。公开 GameMapping.Build 的完整映射计划又与 canonical 源记录独立对照；原 song/options 不突变。

132份谱 JSON＋catalog.db＋7个未改 Core 输入文件组成显式140保护子集（路径清单见integrity JSON）。**140是文件哈希数，不是曲库条目数；catalog与Songs当前132正确。** 全132源文件相同SHA保证原notes也未改，100首POP另有逐曲raw notes指纹前后对照。扩展旧保护快照5,846文件中的父并行生产构建变化单列，不冒称全部不变；旧probe/旧证据/源intake/真实UD分组计数在integrity JSON。

## 旧版12条 selected 端点变化的归因

详见 `matrix-02-selected-release-details.json`，用旧Core `B5E56BEB5ACE8048524EF62617B4445A70F779BEE54FA81935BF117E34B63F4A` 定点重建11组合/22 Build，59断言均通过。全部起音不变，HoldMs与SoundMs同幅缩短：

| 曲/乐器 | 键 | 起音ms | 原时值→开后时值ms | 缩短ms |
|---|---|---:|---:|---:|
|009 voice|H|71182.708|1737.312→1731.124|6.188|
|066 horn/piano/harmonic/voice（4条）|Q|160268.022|1636.362→1628.362|各8.000|
|220 horn|Q|180438.037|3866.903→3862.936|3.967|
|411 horn/piano/harmonic/voice（4条）|Q|186568.266|1427.082→1420.570|各6.512|
|658 horn|Y|97099.972|1801.800→1793.800|8.000|
|658 horn|Y|230064.848|1818.180→1810.180|8.000|

后继新增同键 onset距旧note尾余量依次1.812/0/4.033/1.488/0/0ms；旧映射必须提前8ms释放，缩短=8−余量，属于现有same-key safety。最终8ms尾垫之后，这12及其他selected端点变化全部消失；没有修改检查预期掩盖端点变化。

## 035/038 典型比较与用户手动[1,2]

| 曲目 | 新增完整源音 | 段 | 首起音s 关→开 | >=5s内部note-off休止段 关→开 |
|---|---:|---:|---:|---:|
|035|104：BRIDGE14＋PIANO90|3|14.524641→0.580986|1→0|
|038|78：BRIDGE76＋PIANO2|7|24.343750→0.343750|2→0|

两首在9乐器的源音选择一致，duration没有缩短，仍保留真实小休止。两首用户[1,2]的18组合全部通过：035另接79个原PIANO、038接2个原PIANO；新增BRIDGE为0，已选双声部保留。移调/速度/选轨保存状态不变。onset间隔和note-off休止分别记录，不能把长持续音当空白。

## 592：为何唯一>=5s内部休止保留

100首风物中，**有>=5s内部note-off休止的歌曲87→1（592）；休止段总数127→1**。87不是休止段计数。

592剩余段是 **166.385111–171.904311秒，共5.519200秒**：

1. BRIDGE贪心选择完整原音 pitch75，165.676021秒起、709.090ms长，到166.385111秒。
2. 下一个 BRIDGE pitch67 在166.248747秒已起（原长1627.272ms，到167.876019秒），与上一已选新增音重叠，故整音拒绝。PIANO四音在165.948748秒已起，最长到168.094200秒；也与已选BRIDGE重叠，不能把它们截尾/搬到166.385111秒重奏。
3. 因而前 **1.709089秒** 是贪心单声部选择与完整notes边界共同留下的不可截取音尾，不是全源真实静音。
4. **168.094200–171.904311秒的3.810111秒才是所有非鼓原声部共同真实休止**，直至选中track1恢复。
5. 在整个剩余5.519200秒窗内，未选非鼓源“起止都完整落窗”的候选数=0。此处不是漏了可直接安全接上的起音，也不是8ms垫导致5秒失败；不发明、移位、延长、截断或重奏音符。

分类：**greedy选声部＋整音边界不足前缀＋真实全源休止后缀**，不能全部称源真实休止，也不能为追求全歌零空白强行修音。本轮未修改592、Core或选择算法。详见 `matrix-final-592-rest-analysis.json`。

## 音频和记录：已完成但不是游戏实测

8 WAV：035/038 × windsong/harmonic × smart off/on。每曲两乐器四文件同绝对窗口：035为117028.109–146578.109ms；038为130248.438–159798.438ms。29.550s谱窗＋450ms合成尾，共30.000s，22050Hz/mono16bit、661500样本，无整段静音/饱和采样。边界穿越音仅在试听片段裁剪/重新起音，已记录；PreviewAudio软件包络和各片段gain不认证游戏采样/音质。**只生成，未播放。**

18记录实际调用 PlaybackEngine、仅注入RecordingSink。每个原计划片段<=2000ms，调度时间4倍压缩到500ms；墙钟范围{min(x['wallMs'] for x in ev['recordings']):.3f}–{max(x['wallMs'] for x in ev['recordings']):.3f}ms。事件顺序/批次与预期完全一致，72次按下均释放，held=0，无duplicateDown/orphanRelease。加速只作线程/调度烟测，不是原速音乐时序证据、全曲演奏或真实按键输入验收。

**仍存在的实现边界**：跨900对统计884个新增延音计划音被既有same-key释放逻辑缩短SoundMs（源原notes完整、基底0变化）。没有把“raw起止完全保留”偷换成“所有mapped新增音尾也完全不变”。

## 历史失败、外部验收与交付

- 首次构建中文默认SDK路径编码错误已修新副本并留日志。
- matrix-01有957条oracle不匹配，是sidecar canonical mapping仍带[1]将新增源音再次过滤的错误；已定位修复，首轮和诊断证据保留，matrix-02/final失败0。未改旧probe或Core来凑通过。
- sidecar中间Core全套 `{legacy['cases']-legacy['failures']}/{legacy['cases']}`、4失败保留：2个历史30曲库/迁移计数断言；2个旧无尾垫边界/piano夹具。SmartInterludeTests.cs在该DLL编完6秒后被父更新；这不是最新父191套的记录，不能冒称它通过。按停止扩展要求不再重跑。
- 用户/父报告：191/191 core、14 smartUI、68 baseline、39 auditionUI、132 cold均通过，**归属于父，sidecar未独立重做UI/冷启**。
- 当前部署等待父处理PID17332退出后原位替换；本sidecar未停止进程、未碰部署和UserData。至此停止扩展和验证。

主要文件：`matrix-final.json/.csv`、`matrix-final-slots.json`、`matrix-final-typical.json`、`matrix-final-fixtures.json`、`matrix-final-evidence.json`、18个`matrix-final-evidence-record-*.json`、8个`matrix-final-evidence-*-max30s.wav`、`matrix-final-592-rest-analysis.json`、`matrix-final-integrity.json`、`matrix-final-summary.json`、`matrix-final-delivery-manifest.json`。源码与日志在sidecar目录；所有旧证据不覆盖。
'''
save_text(OUT/'matrix-final-report.md',report)
readme='''# SmartInterludeProbe（隔离离线sidecar）

只写此新目录与 `.validation/smart-interludes-2026-10-06` 的新 `matrix-*` 文件。主入口 public GameMapping.Build；Checks以线性选音/笛卡尔区间交集独立oracle检查raw>=3s资格、physical/arpeggio/8ms尾垫safe slot、原完整对象和映射基底key-onsets/hold/sound。附加内部Arrange只读反射检视用于独立raw note身份与slot证明，不替代公开主接口。

## 已执行（请勿重复覆盖证据）
- Build-Probe.ps1 -IncludeCoreTests：复用Pop100GapProbe脚本新副本，本目录artifacts/nuget/feed/tmp/cli-home隔离。
- Run-Probe.ps1 -Mode matrix -Output <NEW绝对matrix-*.json>：900+66对、300鼓组合，结果final已保存。
- Run-Probe.ps1 -Mode fixtures -Output <NEW绝对matrix-*.json>：38pair+4direct，包括14原生吉他和弦。
- Run-Probe.ps1 -Mode evidence -Output <NEW绝对matrix-*.json>：18 RecordingSink、8 staged software WAV后复制matrix-*；从未使用nativeSink/音频播放。
- Finalize-Reports.py：只读现有结果、源notes与保护哈希，生成报告/592分析/完整性。不得重复覆盖。

Run-CoreTests.ps1是保留的历史直接190套检查（132曲库），不是最新父191套验收。LegacyReleaseDiagnostic.cs.txt保留旧版12条差异的锁定DLL诊断代码；对应结果已保存，不再用新Core重解释旧结果。

最终结论和限制请看 D:\\原神弹琴脚本\\AutoMidiPlayer\\.validation\\smart-interludes-2026-10-06\\matrix-final-report.md；没有部署/UD改动。主矩阵和额外66失败0、selected Hold/Sound变化0；592 residual是真实休止与greedy整音边界混合，不强填。884个added mapped sustain端点缩短仍单列。不做游戏音质/完整音乐证明。

父确认完成后本轮按用户要求已停止，不要自动扩展或重新播放/输入。代码沿用仓库GPL-3.0归属；LICENSE与QINBAN-NOTICES未改。
'''
save_text(TOOL/'README.md',readme)
files=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.glob('matrix-final*')) if p.is_file()]
tool_files=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(TOOL.iterdir()) if p.is_file()]
save('matrix-final-delivery-manifest.json',{'createdAt':datetime.datetime.now().astimezone().isoformat(),'validationFiles':files,'sidecarTopLevelFiles':tool_files,'manifestSelfExcluded':True,'audioPlayed':False,'nativeKeySendAttempts':0,'deploymentChanges':0,'userDataWrites':0})
print('FINAL: requested failures',summary['finalFailureAssertions'],'assertions',summary['finalAssertions'],'protected',len(protected140),'unchanged',sum(x['unchanged'] for x in protected140))
print('EXPANDED: files',len(expanded),'unchanged',sum(x['unchanged'] for x in expanded),'observed parent production differences',len(changed))
print('592 rest',round(end-start,3),'greedy prefix',round(true_rest['startMs']-start,3),'true source silence',round(true_rest['durationMs'],3))
print('DELIVERY:',OUT/'matrix-final-report.md')