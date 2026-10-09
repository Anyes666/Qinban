# 琴伴 QinBan · 原神演奏工作台 0.4.2

<!-- 2026-10-08-current-library-snapshot-v5 -->

## 2026-10-08 最新可核验快照：中文流行优先

source/runtime 曲库均为 **6332 条**，不是旧历史段落中的 6000 条。教学/试听 32、POP909 中文候选 901、midi_lyric_corpus 中文流行 220、callmeyyzx-midi 中文候选 7、CantopopCorpus 粤语候选 105、OpenScoreLieder 357、PDMX 196、MutopiaProject 414、BFDB 4100；距离 20000 还差 **13668 条**。

- 明确带 `zh` 标签的条目共 1128 条（POP909 901 + midi_lyric_corpus 220 + callmeyyzx-midi 7）；明确带 `yue` 的粤语条目 105 条；两首试听谱带 `cmn`。`zh` 与 `cmn` 仍是分组标签，不代替逐首普通话核验。
- 中文/粤语明确标签命中 1235 条（zh/cmn 1130 + yue 105），其中 280 条带透明的 `大众优先` 编辑标签；该标签不是抖音、酷狗或网易云实时榜单认证。
- BFDB 的 4100 条目前没有可靠语种标签；不能把未标注条目全部计作英文歌。后续不再用英文/古典来源填充中文主力指标。
- 曲谱的 `candidate-unverified`、`musicReview=not-reviewed`、`gameReview=not-tested`、`redistributionVerified=false` 状态保持不变；不把索引元数据或来源时序校验冒充版权、人工听辨或原神内验收。
- 曲库页默认进入“中文大众主力（推荐）”筛选，并使用“中文优先”排序：先显示编辑精选的大众中文条目；切换“中文流行候选”可查看完整中文/粤语候选，切换“全部曲库”可查看完整曲库。“中文大众主力”只显示带有透明编辑标签的条目。分页在 SQL 层完成，不把全库谱子读入内存重排。

本段是当前快照；下方 6000 条及更早段落保留为历史记录，不应当前数量。
## 2026-10-07 中文大众候选增量：原位新增 7 首

- 本批原位加入：《青花瓷》《稻香》《孤勇者》《刚好遇见你》《芒种》《热爱 105°C 的你》《杀死那个石家庄人》，P0=5，P1=2。
- 批次使用已有结构化 MIDI 流水线：7/7 源时序对照通过、九种旋律乐器 63 组映射通过，没有新建发行文件夹。
- 本批仍为 `candidate-unverified`：未完成逐首人工听辨、原神内逐曲验收或再分发权利确认。详细证据见 `.validation/callmeyyzx-chinese-batch-20261007/`。

## 2026-10-07 中文主力入口可见性增强

- 曲库首页继续默认落在“中文流行（推荐）”，新增可见范围提示：中文流行、大众中文精选、明确英文和语种未标注数量分别显示，避免把 4100 条未标语种 BFDB 误认为英文。
- “全部曲库”仍保留，用户可以查看完整 6332 条曲库；筛选和分页仍在 SQL 层完成，不会把全库谱子一次性读入内存。
- 已将中文优先批次原位更新到 `D:\原神弹琴脚本\dist\QinBan-0.4.2-smooth-scroll-win-x64`，没有新建生产版本文件夹；`UserData` 未修改，原有 6325 份谱面内容保持不变，仅新增 7 条。
- 发行包 `QinBan.exe` 已在原目录原位更新；旧文件备份于 `.validation/inplace-update-backup-20261007-chinese-priority-v1/QinBan.exe`。
- 验证：核心测试 `193/193`、`25278 assertions`、0 failures；隔离发行包 UI 自测 `69/69`、0 failures、`nativeSendAttempts=0`；当前生产包便携冷启动 `6332/6332` 通过。这些测试不等同于原神内逐首实测或版权清权。
## 2026-10-07 原位更新与中文来源审计补充

- 已将中文优先批次原位更新到 `D:\原神弹琴脚本\dist\QinBan-0.4.2-smooth-scroll-win-x64`，没有新建生产版本文件夹；`UserData` 未修改，原有 6325 份谱面内容保持不变，仅新增 7 条。
- 发行包当前包含 `6332` 条 `entries`、`6332` 条 `search_index`，SQLite `integrity_check=ok`。搜索索引与旧条目保持不变，仅加入 7 条新谱。
- 中文流行默认筛选为 `1235` 条，严格“中文大众主力”筛选为 `280` 条；“全部曲库”仍可访问全库，不把未标语种条目自动归为英文或中文。
- 原位包 UI 自测 `69/69` 通过，`nativeSendAttempts=0`；便携冷启动 `6332/6332` 通过；核心测试 `193/193` 通过、`25278` assertions、0 failures。这些软件级验证均不等同于原神内逐首演奏验收。
- 本轮审计了四类中文来源：`callmeyyzx/midi`（66 个 MIDI/NBS，15 个中文文件名候选）、`Chinese-Songs-Midi-Dataset`（仓库 README 声称近 3000 首）、`àiSong Dataset`（2323 个结构化片段）和 CCMUSIC/OpenCpop 等中文流行数据源；因缺少歌曲数据再分发授权、缺少歌手/版本字段或访问协议限制，均未冒充生产内置谱。
- 审计清单：`catalog-intake/chinese-source-audit-20261007-v1/manifest.json`；各来源独立证据位于 `catalog-intake/callmeyyzx-midi-20261007/`、`catalog-intake/chinese-songs-midi-dataset-20261007/`、`catalog-intake/aisong-dataset-20261007/`。
- 下一批只有在取得明确的歌曲数据再分发许可或用户授权，同时补齐歌名、歌手、语言、作品/版本 ID、可验证时值后，才可进入 productionBuiltin；否则只保留 research candidate。
## 2026-10-07 中文流行优先纠偏（元数据层）

用户反馈指出此前 BFDB 批次以英文/未知语言条目为主，不符合“中文流行歌为主、抖音/酷狗/网易云大众歌曲优先”的目标。本次已停止继续安装暂存的 BFDB v25 英文批次，并对现有 901 条 POP909 结构化条目做了**仅元数据、不改音符**的纠偏：

- 901 条 POP909 条目统一增加 `zh` 编辑分组、`中文歌曲` / `中文流行候选` 标签和可检索的版本标签；
- 其中 162 条命中透明的主流歌手/大众歌名优先集合，标记为 `中文流行` + `大众优先`；包含《日不落》《美人鱼》之外的周杰伦、林俊杰、蔡依林、五月天、陈奕迅、邓紫棋、薛之谦、毛不易、周深等主流歌手条目；
- `zh` 是为了检索和分组的编辑分类，POP909 源索引没有逐条声明语言；不能把它当作权威语言核验；
- 现阶段仍保持 `candidate-unverified`、`musicReview=not-reviewed`、`gameReview=not-tested`、`redistributionVerified=false`，不把索引元数据或来源时序校验冒充版权、人工听辨或原神内验收；
- 源码曲库与运行包仍各 6000 条、JSON 与 catalog 字节一致；只更新 source/runtime 的 POP909 元数据，EXE、UserData 和未安装的 BFDB v25 均未动。

证据：`catalog-intake/chinese-pop-metadata-2026-10-07-v1/manifest.json`、`.validation/chinese-pop-metadata-2026-10-07-v1/apply-report.json`。后续新增批次必须优先满足中文流行来源和元数据准入，不再用英文/古典条目填充中文主力指标。

## 2026-10-07 当前快照：6000条（BFDB v24 已完成并安装）

当前真实 source/runtime/stage 曲库为 **6000 条**：教学/试听 32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 4100；结构化来源候选（不含教学/试听）为 **5968**，距 20000 还差 **14000**。本轮沿用 add-only 流水线完成 **v23：5600→5800** 与 **v24：5800→6000**，两批各 200 条。

### 版本与去重

- 每条新增谱都保留 `WorkId`（作品归并）、`EditionId`（具体版本）和 `VersionLabel`（界面展示版本）；不同编配/来源允许共存，但必须使用不同 `EditionId`、来源哈希和清晰版本标签。
- v23、v24 各自均为 200 个唯一 WorkId、200 个唯一 EditionId、200 个唯一来源 SHA256；两批的 `versionGroupCount=200`、`repeatedVersionGroups=0`，本两批没有发现同一 WorkId 的第二版本。没有为了凑数复制条目。
- 当前 6000 条中版本标签缺失/冲突为 0，EditionId 重复为 0，来源 SHA256 重复为 0。

### v23/v24 证据路径

- v23 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intakefdb-2026-10-06atch-200-2026-10-07-v23`；build retry1：`D:\原神弹琴脚本\AutoMidiPlayer\.validationfdb-200-build-2026-10-07-v23-retry1`；独立校验：`D:\原神弹琴脚本\AutoMidiPlayer\.validationfdb-200-independent-2026-10-07-v23-retry1.json`；安装/完整性：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updatesfdb-200-postinstall-2026-10-07-v23-retry1.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-5800-2026-10-07-v23-retry1-v2.json`。
- v24 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intakefdb-2026-10-06atch-200-2026-10-07-v24`；build：`D:\原神弹琴脚本\AutoMidiPlayer\.validationfdb-200-build-2026-10-07-v24`；独立校验：`D:\原神弹琴脚本\AutoMidiPlayer\.validationfdb-200-independent-2026-10-07-v24.json`；preflight/apply/postinstall：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updatesfdb-200-preflight-2026-10-07-v24.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updatesfdb-200-apply-2026-10-07-v24.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updatesfdb-200-postinstall-2026-10-07-v24.json`；完整性：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-6000-2026-10-07-v24.json`。
- v23 首次 build 由于旧 DLL 的 120 秒 owned restart helper timeout 失败，未安装；retry1 使用源码已有的 600 秒 timeout 通过，失败证据保留且未发布。

### 回归边界

- v24 build/independent source timing、preflight、正常 apply、postinstall、6000 条 source/runtime 完整性、冷启动均通过；source/runtime JSON 与 catalog 字节一致，既有 5800 条未改变。
- 最新 core：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T060251065\core-test-report.json`，191 cases / 24264 assertions / 0 failures，recording sink only，无 Windows 原生按键。
- 当前生产 EXE 的程序化 UI 测试仍记录 68 cases / 8 failures，集中在大曲库异步列表/元数据验证；已有修复版在隔离目录验证为 68/68，但尚未替换生产 EXE。当前 EXE SHA256 未改变，UserData 未改变，也未新建生产发行目录。

### v25 已准备但未安装

v25 已完成 200 条新候选 intake（`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intakefdb-2026-10-06atch-200-2026-10-07-v25`），未 build、未 apply；`uniqueSourceSha256=200`、`uniqueEditionIds=200`、`uniqueWorkIds=200`、`conversionFailureCount=6846`，仍为 `candidate-unverified / not-reviewed / not-tested / redistributionVerified=false`。下一步须先 build、独立校验和 preflight，再决定是否安装。

本快照不宣称已覆盖抖音/酷狗热门歌，不宣称 BFDB 候选已人工听辨、原神内验收或取得再分发权。来源、音符与版权状态必须以各自 intake 和报告为准；结构/时序通过不等于音乐质量通过。


## 2026-10-07 当前快照：5600条（BFDB v22 已完成并安装）

当前真实 source/runtime/stage 曲库为 **5600 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 3700；结构化来源候选为 **5568**，距20000还差 **14400**。v22 完成 5400→5600。

v22 的 build、独立 source timing、preflight、正常 apply、postinstall、integrity、隔离 UI/cold-start 和 core test 均通过。当前边界仍是 **候选未清权、未人工试听、未原神内实测**，不宣称 BFDB 为热门流行歌，也不宣称音乐质量或版权/再分发权利已通过。

### BFDB v22 实际报告路径

- v22 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v22`；manifest `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v22\manifest.json`；acquisition `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v22\acquisition-report.json`；version groups `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v22\version-groups.json`。
- v22 build：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v22`，报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v22\build-report.json`；independent `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v22.json`；preflight `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v22.json`。
- v22 apply：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v22.json`，状态 `PASS`、`applied=true`；postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v22.json`；integrity `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-5600-2026-10-07-v1.json`。
- v22 isolated UI `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-5600-2026-10-07-v1\ui-test-report.json`（68/68）；cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-5600-2026-10-07-v1\cold-start-report.json`；最新 core test `D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T042854694\core-test-report.json`（191 cases / 23064 assertions / 0 failures，recording sink only）。

本次仅更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake；v18-v21 历史以及 v20 failed/retry 历史均保留。
## 2026-10-07 历史快照：5400条（BFDB v21 已完成并安装）

当前真实 source/runtime/stage 曲库为 **5400 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 3500；结构化来源候选为 **5368**，距20000还差 **14600**。v21 完成 5200→5400。

v21 的 build、独立 source timing、preflight、正常 apply、postinstall、integrity、隔离 UI/cold-start 和 core test 均通过。当前边界仍是 **候选未清权、未人工试听、未原神内实测**，不宣称 BFDB 为热门流行歌，也不宣称音乐质量或版权/再分发权利已通过。

### BFDB v21 实际报告路径

- v21 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v21`；manifest `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v21\manifest.json`；acquisition `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v21\acquisition-report.json`；version groups `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v21\version-groups.json`。
- v21 build：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v21`，报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v21\build-report.json`；independent `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v21.json`；preflight `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v21.json`。
- v21 apply：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v21.json`，状态 `PASS`、`applied=true`；postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v21.json`；integrity `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-5400-2026-10-07-v1.json`。
- v21 isolated UI `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-5400-2026-10-07-v1\ui-test-report.json`（68/68）；cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-5400-2026-10-07-v1\cold-start-report.json`；最新 core test `D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T040151802\core-test-report.json`（191 cases / 22464 assertions / 0 failures，recording sink only）。

本次仅更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake；v20 的 failed/retry 历史以及 v19/v18 历史边界均保留。## 2026-10-07 历史快照：5200条（BFDB v20-retry1 已完成并安装）

当前真实 source/runtime/stage 曲库为 **5200 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 3300；结构化来源候选按预计台账为 **5168**，距20000还差 **14800**。v20-retry1 完成 5000→5200。

原 v20 批次选出200条，但在严格 preflight 阶段因 exact title collision 被拒绝，未 apply、未写入生产；该批 intake/build/independent 证据和失败原因保留。随后 v20-retry1 使用排除 v1-v20 的来源重新选取200条并正常 apply。当前边界仍是 **候选未清权、未人工试听、未原神内实测**，不宣称 BFDB 为热门流行歌，也不宣称音乐质量或版权/再分发权利已通过。

### BFDB v20 原批次与 v20-retry1 实际报告路径

- 原 v20 未安装批次：intake `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v20`；build `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v20`，报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v20\build-report.json`；independent `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v20.json`。严格 preflight 失败原因：exact title collision，标题为 `John Malchair’s Third Collection of Tunes`；未 apply、未安装。未发现独立的 `bfdb-200-preflight-2026-10-07-v20.json` 文件，因此不补写虚构路径。
- v20-retry1 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v20-retry1`；build `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v20-retry1`，报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v20-retry1\build-report.json`；independent `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v20-retry1.json`；preflight `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v20-retry1.json`。
- v20-retry1 apply：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v20-retry1.json`，状态 `PASS`、`applied=true`；postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v20-retry1.json`；integrity `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-5200-2026-10-07-v1.json`。
- v20-retry1 isolated UI `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-5200-2026-10-07-v1\ui-test-report.json`（68/68）；cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-5200-2026-10-07-v1\cold-start-report.json`。v20 未新增 core test；最新已有 core report 为 v19 路径 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T030915133\core-test-report.json`，仅作为既有报告，不冒充 v20 专属验证。

本次仅更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake；v18/v19 台账与历史证据保留。## 2026-10-07 历史快照：5000条（BFDB v19 已完成并安装）

当前真实 source/runtime/stage 曲库为 **5000 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 3100；结构化来源候选按预计台账为 **4968**，距20000还差 **15000**。v19 完成 4800→5000。

v19 的 build、独立 source timing、preflight、正常 apply、postinstall、integrity、隔离 UI/cold-start 和最新 core recording-sink test 均有实际报告。apply 报告状态为 **PASS** 且 `applied=true`。当前边界仍是 **候选未清权、未人工试听、未原神内实测**，不宣称 BFDB 为热门流行歌，也不宣称音乐质量或版权/再分发权利已通过。

### BFDB v19 实际报告路径

- v19 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v19`；manifest `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v19\manifest.json`；acquisition `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v19\acquisition-report.json`；version groups `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v19\version-groups.json`。
- v19 build：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v19`；报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v19\build-report.json`；独立 source timing `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v19.json`；preflight `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v19.json`。
- v19 apply：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v19.json`，状态 `PASS`、`applied=true`；postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v19.json`（PASS）。
- v19 integrity：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-5000-2026-10-07-v1.json`；isolated UI `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-5000-2026-10-07-v1\ui-test-report.json`（68/68）；cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-5000-2026-10-07-v1\cold-start-report.json`；最新 core test `D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T030915133\core-test-report.json`（191 cases / 21264 assertions / 0 failures，recording sink only）。

本次仅更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake；v18 台账与历史证据保留。## 2026-10-07 历史快照：4800条（BFDB v18 recovery 已完成并安装）

当前真实 source/runtime/stage 曲库为 **4800 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 2900；结构化来源候选按真实台账为 **4768**，距20000还差 **15200**。v18 完成 4600→4800。

v18 的 build、独立 source timing、preflight、recovery source-catalog switch、recovery postinstall、integrity、隔离 UI/cold-start 和 core recording-sink test 均有实际报告；原始 apply 报告存在但为 **0 字节**，不能记为 apply PASS，最终 postinstall PASS 属于 recovery evidence。当前边界仍是 **候选未清权、未人工试听、未游戏测试**，不宣称 BFDB 为热门流行歌，也不宣称音乐质量、原神内播放或版权/再分发权利已通过。

### BFDB v18 实际报告路径

- v18 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v18`；manifest `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v18\manifest.json`；acquisition `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v18\acquisition-report.json`；version groups `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v18\version-groups.json`。
- v18 build：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v18`；报告 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v18\build-report.json`；独立 source timing `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v18.json`；preflight `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v18.json`。
- v18 原始 apply：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v18.json`，实际 **0 字节**，不作为 apply PASS；recovery switch `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v18\recovery-source-catalog-switch.json`；初次 recovery postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-recovery-2026-10-07-v18.json`（FAIL_INSTALLATION_CHECK）；最终 recovery postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-recovery-2026-10-07-v18-rerun-v1.json`（PASS）。
- v18 integrity：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-4800-2026-10-07-v1.json`；isolated UI `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-4800-2026-10-07-v2\ui-test-report.json`（68/68）；cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-4800-2026-10-07-v1\cold-start-report.json`；core test `D:\原神弹琴脚本\AutoMidiPlayer\.validation\core-0.4.2-20261007T024859183\core-test-report.json`（191 cases / 20664 assertions / 0 failures，recording sink only）。

### 历史证据范围修正

- v16 已保留 intake、build、独立 source timing、preflight、apply、postinstall；未发现单独的 4400 integrity、isolated UI 或 cold-start 报告，不能用 4600 报告倒推 v16 专属证据。
- v17 的 intake、build、独立 source timing、preflight、apply、postinstall，以及实际存在的 4600 integrity/UI/cold-start 路径仍保留在历史台账/文档中。v13、v15、v17 台账不覆盖、不改写。

本次只更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake；不开始 v19。## 2026-10-07 历史快照：4200条（BFDB v14/v15 已完成并安装）

当前真实源码/运行曲库为 **4200 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 2300；结构化来源候选按当前真实台账为 **4168**，距20000还差 **15800**。v14 完成 3800→4000，v15 完成 4000→4200。

v14 初次 build 曾保留失败证据，随后 retry 成功；v15 直接完成。当前边界仍是 **候选未清权、未人工试听、未游戏测试**，构建/独立源时序/安装/完整性及 isolated UI/cold-start 报告不等于逐首音乐审校、原神内游戏验收或权利清权。

### BFDB v14/v15 实际报告路径

- v14 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-06-v14`；初次 build `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v14`；retry build `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v14-retry`；独立 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v14.json`；preflight/apply/postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v14.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v14.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v14.json`；integrity `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-4000-2026-10-07-v1.json`；isolated UI/cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-4000-2026-10-07-v2\ui-test-report.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-4000-2026-10-07-v1\cold-start-report.json`。
- v15 intake：`D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-07-v15`；build `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v15`；独立 `D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v15.json`；preflight/apply/postinstall `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v15.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v15.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v15.json`；integrity `D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-4200-2026-10-07-v1.json`；isolated UI/cold-start `D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-ui-4200-2026-10-07-v1\ui-test-report.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\portable-cold-start-4200-2026-10-07-v1\cold-start-report.json`。

本次只更新文档/台账，不修改 Songs、EXE、UserData、代码或 catalog-intake。

## 2026-10-07 历史快照：3800条（BFDB v13 已完成）

当前真实生产/运行曲库为 **3800 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 1900；结构化来源候选 **3768**，距20000还差 **16200**。BFDB v13 本批实际新增200条，阶段从3600条增至3800条。

v13 构建、独立 source timing、preflight、apply、postinstall 和完整性报告均为 PASS。当前边界仍是 **候选未清权、未人工试听、未游戏测试**；这些报告不等于逐首音乐审校、原神内游戏验收或权利清权。

### BFDB v13 实际报告

- intake：沿用已有 `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-06-v13`。
- 构建：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-build-2026-10-07-v13`。
- 独立 source timing：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\bfdb-200-independent-2026-10-07-v13.json`。
- preflight/apply/postinstall：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-preflight-2026-10-07-v13.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-apply-2026-10-07-v13.json`、`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-updates\bfdb-200-postinstall-2026-10-07-v13.json`。
- 最新完整性：`D:\原神弹琴脚本\AutoMidiPlayer\.validation\library-integrity-3800-2026-10-07-v1.json`。

本次只同步文档/台账，不启动 v14，不修改 Songs、EXE、UserData、代码或 catalog-intake。

## 2026-10-07 历史快照：3600条（BFDB v12-retry 安装完成）

当前真实生产/运行曲库为 **3600 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 1700；结构化来源候选 **3568**，距20000还差 **16400**。v12 intake 复用并保留原 intake，修复验证器后以 v12-retry 成功安装200条（3400→3600）。

v12 初次构建状态为 `FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH`，仅是 PopBatchTool 验证器的分页假失败：同一 WorkId 有86个版本时，旧版 BuildRunner 只查前50条，未安装、未写入生产。修复后 BuildRunner.cs 按分页查找版本，v12-retry 的独立 source timing、preflight、apply、postinstall、integrity 全部 PASS。

当前边界仍是 **候选未清权、未人工试听、未游戏测试**；结构/时序、安装和完整性报告不等于音乐审校、原神内游戏验收或权利清权。BuildRunner.cs 修复属于主线已有代码变更，本次只同步文档/台账，不修改代码、Songs、EXE、UserData 或 catalog-intake。

### v12 初次失败与 v12-retry 报告

- v12 初次失败证据：`.validation\bfdb-200-build-2026-10-06-v12\build-report.json`，状态 `FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH`；原因是同一 WorkId 的86个版本超过旧验证器前50条分页上限，造成伪失败。
- v12-retry：构建 `.validation\bfdb-200-build-2026-10-07-v12-retry`；独立 source timing `.validation\bfdb-200-independent-2026-10-07-v12-retry.json`；preflight/apply/postinstall `.validation\library-updates\bfdb-200-preflight-2026-10-07-v12-retry.json`、`.validation\library-updates\bfdb-200-apply-2026-10-07-v12-retry.json`、`.validation\library-updates\bfdb-200-postinstall-2026-10-07-v12-retry.json`；完整性 `.validation\library-integrity-3600-2026-10-07-v2.json`。

代码修复记录：`tools/PopBatchTool/BuildRunner.cs` 改为按分页查找版本，消除同一 WorkId 多版本超过50条时的伪失败；本次未修改代码。

## 2026-10-07 历史快照：3400条（BFDB v11 已安装；v7/v10 失败不计入生产）

当前真实生产/运行曲库为 **3400 条**：教学/试听32、POP909 901、OpenScore Lieder 357、PDMX 196、Mutopia 414、BFDB 1500；结构化来源候选 **3368**，距20000还差 **16600**。已安装批次为 v6=200（2600→2800）、v8=200（2800→3000）、v9=200（3000→3200）、v11=200（3200→3400）。

失败 intake 不计入生产：v7 200候选构建 `FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH`，`Poll’s Whim / JJo3.133` 参考 BPM=630 超出20–400，未安装；v10 intake 200在 manifest 验证阶段因标题含 C1 控制字符（`John Malchair\x92s...`）失败，未安装。当前边界仍是 **候选未清权、未人工试听、未游戏测试**，不宣称热门歌曲覆盖或人工/游戏验收。

### v8/v9/v11 与 3400 完整性证据

- v8：intake `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-06-v8`；独立构建/源时序 `.validation\bfdb-200-build-2026-10-06-v8`、`.validation\bfdb-200-independent-2026-10-06-v8.json`；preflight/apply/postinstall `.validation\library-updates\bfdb-200-preflight-2026-10-06-v8.json`、`.validation\library-updates\bfdb-200-apply-2026-10-06-v8.json`、`.validation\library-updates\bfdb-200-postinstall-2026-10-06-v8.json`；完整性 `.validation\library-integrity-3000-2026-10-06-v1.json`。
- v9：intake `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-06-v9`；独立构建/源时序 `.validation\bfdb-200-build-2026-10-06-v9`、`.validation\bfdb-200-independent-2026-10-06-v9.json`；preflight/apply/postinstall `.validation\library-updates\bfdb-200-preflight-2026-10-06-v9.json`、`.validation\library-updates\bfdb-200-apply-2026-10-06-v9.json`、`.validation\library-updates\bfdb-200-postinstall-2026-10-06-v9.json`；完整性 `.validation\library-integrity-3200-2026-10-06-v1.json`。
- v11：intake `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\bfdb-2026-10-06\batch-200-2026-10-06-v11`；独立构建/源时序 `.validation\bfdb-200-build-2026-10-06-v11`、`.validation\bfdb-200-independent-2026-10-06-v11.json`；preflight/apply/postinstall `.validation\library-updates\bfdb-200-preflight-2026-10-06-v11.json`、`.validation\library-updates\bfdb-200-apply-2026-10-06-v11.json`、`.validation\library-updates\bfdb-200-postinstall-2026-10-06-v11.json`；完整性 `.validation\library-integrity-3400-2026-10-07-v1.json`。
- 当前完整性/UI/冷启动：`.validation\library-integrity-3400-2026-10-07-v1.json`；`.validation\portable-ui-3400-2026-10-07-v1\ui-test-report.json`（68/68）；`.validation\portable-cold-start-3400-2026-10-07-v1\cold-start-report.json`；`.validation\portable-cold-start-runtime-3400-2026-10-07-v1\cold-start-report.json`。

代码准入修复属于主线已有变更，本次不改代码：`tools/acquire_bfdb_batch.py` 已有 BPM 20–400/finite 校验及标题/歌手/VersionLabel 控制字符拒绝，`tools/test_acquire_bfdb_batch.py` 4 tests passed。

## 2026-10-06 历史快照：2600条（BFDB v5 本轮新增200）

在既有2400条曲库基础上，沿用同一结构化谱流水线从固定来源继续加入200条 BFDB v5 候选；源码曲库和既有 two-song-pilot 运行目录现均为2600条。当前来源构成为：32条教学/试听、901条 POP909、357条 OpenScore Lieder、196条 PDMX、414条 MutopiaProject、700条 BFDB ABC→MIDI 候选。各来源的 WorkId、EditionId、VersionLabel 和证据边界均保留。
仍使用既有 QinBan 运行目录，BFDB v5 只增量更新既有 Songs 与 catalog.db；EXE、UserData、既有条目和发行目录边界由独立报告复核，没有新建发行目录。
本轮 BFDB v5 清单/来源/版本标记见 `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intakefdb-2026-10-06atch-200-2026-10-06-v5`；构建、独立来源时序、预检、安装后、2600条完整性、UI 和冷启动报告见 `.validation/bfdb-200-build-2026-10-06-v5`、`.validation/bfdb-200-independent-2026-10-06-v5.json`、`.validation/library-updates/bfdb-200-preflight-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v3.json`、`.validation/library-integrity-2600-2026-10-06-v1.json`、`.validation/portable-ui-2600-2026-10-06-v2`、`.validation/portable-cold-start-2600-2026-10-06-v1`、`.validation/portable-cold-start-runtime-2600-2026-10-06-v1`。
BFDB v5 已完成来源转换、结构/时序校验、add-only 安装和软件级验证；仍不是2600首逐首人工试听、原神内逐首游戏测试、热门歌曲覆盖证明或已清权的可公开再分发曲库。

以下100首/30首/候选0取得等文字保留为原阶段历史说明，不是当前数量。


## 2026-10-06 BFDB v5 追加批次：新增200条 ABC 转 MIDI 候选

- v5 实际 `selectedCount=200`，固定来源候选成员 `candidateMemberCount=13835`；唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=200`，`version-groups.json` 共200组，`repeatedVersionGroups=0`。
- 失败记录共663条：500条去重失败、163条转换或结构校验失败；失败项完整保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v5/acquisition-report.json`，没有用标题占位或重复编配凑数。
- 阶段从2400条增至2600条。构建报告明确为数值/结构和本地来源证据，不是音乐审校；当前状态为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。
- 未人工试听、未游戏测试、候选未清权；UI、冷启动和 add-only 报告只证明软件/文件系统边界，不改变上述候选状态。

## 2026-10-06 BFDB v4 历史批次：新增200条 ABC 转 MIDI 候选

- 来源为 Zenodo 记录 `14692025` 的 BFDB British Folk Database；本批仅使用固定本地归档的 13,835 个 ABC 成员和本地 `music21 9.9.2`，确定性选出并转换 200 条。
- v4 实际 `selectedCount=200`，唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=200`；本批 `version-groups.json` 共 200 组，没有重复版本组。`WorkId` 用于同一作品归并，`EditionId` 用于具体来源/编配版本唯一识别，`VersionLabel` 只描述版本/来源，不用来替代哈希去重。
- v4 失败记录共 452 条：300 条 `dedupe/duplicate EditionId`，152 条 `convert-or-validate` 转换或结构校验失败；失败记录保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v4/acquisition-report.json`，没有用标题占位或修补坏谱凑数。
- 曲库阶段从 2200 条增至 2400 条；独立报告确认来源字节/时序、add-only 文件系统和目录完整性边界，未进行人工听辨、原神内逐曲测试或版权清权。
- 本批状态仍为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。验证报告见 `.validation/bfdb-200-independent-2026-10-06-v4.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v2.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v2.json`、`.validation/library-integrity-2400-2026-10-06-v1.json`、`.validation/portable-ui-2400-2026-10-06-v1/ui-test-report.json`、`.validation/portable-cold-start-2400-2026-10-06-v1/cold-start-report.json`.

## 2026-10-06 BFDB v3 历史批次：新增200条 ABC 转 MIDI 谱

- 来源仍为 Zenodo 记录 `14692025` 的 BFDB British Folk Database；本批从固定本地归档的 13,835 个 ABC 成员中确定性扫描，使用本地 `music21 9.9.2` 转换，并通过独立 `smf_reference.parse_smf` 校验 200 条。
- 本批唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=197`；3 个 WorkId 各包含 2 个不同版本，均通过 `VersionLabel` 标清，不把版本重复计作新的 WorkId。
- 失败记录共 240 条（100 条与既有 BFDB intake 重复、140 条转换/结构校验失败），完整保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v3/acquisition-report.json`，没有用标题占位或修补坏谱凑数。
- 安装前曲库为 2000 条，安装后源码 `Songs` 与 `dist/QinBan-0.4.2-two-song-pilot-win-x64/Songs` 均为 2200 条；没有新建发行目录，EXE、UserData 与既有条目保持不变。
- 本批仍为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`；结构和乐器矩阵通过不等于人工听辨、原神内逐曲验收或版权清权。
- intake、构建、独立来源时序检查和安装后检查见：`catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v3`、`.validation/bfdb-200-independent-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v1.json`。

## 2026-10-06 BFDB 100条历史候选批次：新增 ABC 转 MIDI 谱


- 来源为 Zenodo 记录 `14692025` 的 BFDB British Folk Database；本地归档包含 13,835 个 ABC 文件，本轮确定性扫描后成功转换并通过独立 SMF 解析100条，另有115条转换/结构校验失败保留在 intake 报告中，未强行入库。
- 使用本地 `music21 9.9.2` 将 ABC 转为 MIDI，再由 `smf_reference.parse_smf` 独立检查音符、时长与时序；`WorkId`、`EditionId`、`VersionLabel` 和原始 ABC/CSV 证据均保留。
- 安装前曲库为1900条，安装后源码 `Songs` 与 `dist/QinBan-0.4.2-two-song-pilot-win-x64/Songs` 均为2000条；没有新建发行目录，EXE、UserData 与既有条目保持不变。
- 该批状态为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。Zenodo 数据集声明为 CC BY-NC 4.0，不自动等同于底层民歌或软件捆绑再分发清权；本批不宣称人工听辨、原神内测试或可公开发布。
- intake、构建、独立来源时序检查和安装后检查见：`catalog-intake/bfdb-2026-10-06/batch-100-2026-10-06-v2`、`.validation/bfdb-100-independent-2026-10-06-v1.json`、`.validation/library-updates/bfdb-100-postinstall-2026-10-06-v1.json`。
## 当前批次：POP909剩余可准入的601首

- POP909索引共909条；此前已收录300条，本批新增601条，另有8条因源时长预算或冲突同时tempo被拒绝，未强行入库。
- 同一作品按 `WorkId` 归并，具体来源/编配按唯一 `EditionId` 区分；来源标题明确包含 DJ、原版、新版、影视/主题等标记时写入 `VersionLabel`。例如《一剪梅 DJ费玉清》标为“DJ版”，《心痛2009新版》标为“新版”，《日不落》标为“POP909来源演唱/编配版”。完整版本组见 intake 目录的 `version-groups.json`。
- 本批重复 EditionId=0、重复源SHA=0；来源未声明语种的条目保留为未知，不根据歌名或歌手猜测语言。
- 这601条只完成来源时序比较、规范化往返、目录哈希、智能衔接/乐器矩阵和离线UI验证；人工听辨、真实游戏演奏和商业歌曲再分发权利仍未完成。


## 前序阶段：100首来源曲库增量（历史记录）

该阶段曾将源码 Songs 和既有运行目录从32条增加到132条（原30教学+2试听+100真实POP909来源谱）。EXE不变，源时序独立对照通过；本段只保留工程历史，不代表当前数量。当前清单、使用方法、原目录更新及测试边界见 catalog-intake/pop100-2026-10-06/README.md。



这是可运行的 Windows x64 离线桌面版本，不是网页演示。实现参考 AutoMidiPlayer，并移植原神键位 / 八度折叠逻辑；上游原工程保留未改。琴伴只编译 QinBan.* 项目，不会运行上游的管理员启动、账号、遥测或更新服务。不是原神或 Auto MIDI Player 官方软件。



## 最快启动



- 工作区根目录双击 `启动琴伴 0.4.2.cmd`，或运行 `dist/QinBan-0.4.2-win-x64/QinBan.exe`。旧 0.1.0 / 0.2.0 / 0.3.0 / 0.4.0 / 0.4.1 与其 UserData 保留，不自动迁移。

- 便携 ZIP 先完整解压，然后双击包内 `Start-QinBan.cmd` 或 `QinBan.exe`。必须保留 Songs、许可及说明文件。

- 运行时已随软件打包，不要求安装 Python 或 .NET SDK。本机 Windows x64 已做启动和 WPF 界面验证，其他机器 / Windows 版本尚未实测。

- 默认只有本地试听，不自动连接游戏、不发送按键、不要求管理员权限。

- 未制作安装器或代码签名。如系统拦截，先检查交付校验值，不要为运行软件关闭系统防护。



## 当前阶段状态：2600条本机曲库，仍不是两万首正式歌库



当前源码和原运行目录包含2600条：32条既有教学/试听、901条POP909、357条OpenScore Lieder、196条PDMX、414条Mutopia、700条BFDB ABC转MIDI候选。除既有教学/试听外，当前有2568条结构化来源候选；20k/50k压力目录和10k/100k音符夹具不随包收录，也不算真实歌。当前新增条目仍处于来源时序比较、待人工音乐审核状态，不能把“能加载和适配”表述成“原曲精确还原”。BFDB数据集声明为CC BY-NC 4.0，底层曲目和本机捆绑范围仍未完成权利清权。



0.4.1 解决的是工程关卡：曲谱读取/适配在单飞后台任务中完成，快速切曲或改参数只应用最后请求；未就绪时点击或热键不会排队后自动播放。F9、停止、换乐器、切曲可以取消准备。文件解析本身不能强制中断，完成后会检查取消状态并丢弃旧结果。



长试听改为固定 192 KiB 采样缓冲区及磁盘暂存，保持全曲统一增益。这个数字不是软件总内存；10 分钟试听最高约需 79.4 MB 暂存/WAV磁盘空间。完成、停止和取消只清理本次生成的文件；断电/强杀残留没有自动清扫。



## 每首谱的歌手、语种与版本（0.4.2）



- 记录多个歌手、多个语言标签、专辑与演唱/编配版本；谱作者与歌手不混用。同名但不同歌手版本可分别查询，仍按独立作品身份去重，不能自动增加歌数。

- 列表和当前谱显示歌手/语种/版本，完整信息与作者、专辑可在提示及来源面板查看；组合搜索可使用“歌手 语种 版本/专辑”。来源没有的信息显示歌手未标注、语种未知，不推测。

- 教学谱与旧个人谱缺字段仍兼容；原30教学谱音符/文件不改、不伪填流行歌手。

- 工坊TXT新增 `ARTISTS=歌手甲|歌手乙`、`LANGUAGES=cmn|en`、`ALBUM=专辑`、`EDITION=现场版`。旧TITLE/AUTHOR/BPM/FORMAT兼容。无依据时ARTISTS留空、LANGUAGES=und。

- JSON使用provenance.artists、languageTags、album、versionLabel；`author`仍是作者。语种仅作元数据，不参与改音高/时值。 原生 notes JSON 和带 provenance 的 songNotes JSON 均保留身份字段；songNotes 缺 durationMs 时仍明确提示未知音长，不因元数据齐全而认证音乐准确。

- 本轮固定归档覆盖POP909索引909条，其中901条已进入本机Songs（含此前300条与本批601条），8条因解析预算/tempo冲突保留在拒绝清单，不装入Songs。语种、录音版本和作品身份只按来源明确字段记录；未知字段不推测。完整来源与哈希见catalog-intake/pop909-remaining-2026-10-06-v2。



## 已实现



1. 曲库：2200条内置谱（32条既有教学/试听 + 901条POP909 + 357条OpenScore + 196条PDMX + 414条Mutopia + 300条BFDB候选）、中文/歌手/别名/拼音/首字母组合搜索、50项分页、排序、批量收藏、歌单、最近播放、导入筛选和试听队列。

2. 导入：MIDI / TXT / JSON；多文件、当前层文件夹批量导入、拖入文件；SHA256 相同文件不重复添加。

3. 演奏参数：0.25–3 倍速、首段目标 BPM、±24 半音移调、±2 八度、半音处理、音域折叠 / 跳过。

4. 和弦：同时按下、上行琶音、下行琶音、最高旋律音；1–10 音限制，0–150ms 琶音间隔，20–250ms 固定触键；延音乐器默认按谱保持长短音。

5. MIDI：保留全文件变速时间，选择轨道，默认排除第 10 通道打击乐；不把任意 MIDI 视为可原样弹奏。

6. 试听：本地生成 WAV，用 WPF MediaPlayer 播放；音量、暂停、进度定位、段落循环；有按所选乐器变化的音符时间轴与键位高亮，键位可单独试听。

7. 工坊：编辑键位谱、数字简谱、精确 JSON；校验试听；保存为新谱，绝不覆盖导入源文件。时间轴目前为只读可视化，不支持鼠标拖拽编辑音符。

8. 导出：标准化原谱 JSON / MIDI，不把演奏适配参数写回；MIDI 导出保留音符轨道与打击乐标识，采用单一基础 BPM 但保持音符绝对时刻。不会完整保留原始 MIDI 的音色、控制器、踏板和 tempo 事件结构。原始导入文件副本仍在 originals。

9. 输入保护：选定原神进程、显式风险确认、会话级快捷授权、Shift+Enter 松键即开始（无倒计时）、前台/修饰键检查、停止释放按键、F8 暂停 / F9 停止、同数据目录单实例。

10. 乐器：真实图标选择、9 种旋律配置、14/21 键与特殊降音调式，吉他已有同拍和弦自动匹配；3 种鼓类待核验禁用。详情及图标缺项见 INSTRUMENTS.md。



11. 外观：简洁双栏、可收起的演奏调校；两张内置背景与纯净深色；本地 PNG / JPG / JPEG / BMP 导入、整体背景、自动配色、等比裁切 / 完整显示、主体位置、暗化、模糊和面板实度。详见 APPEARANCE.md（便携包为“外观与背景.md”）。



## 外观背景，三步设置



1. 左侧点 **外观背景**（也可点右上“外观”），选择“星夜”“霓蓝”或“纯净深色”。

2. 自定义图片点 **选择本地图片…**，或直接拖入一张图片。文件不会上传；只在新版 UserData/backgrounds 写入一个去除附带元数据的 PNG 副本，原图不修改。最大 20 MiB。

3. 默认等比铺满，可用横 / 纵主体位置调整裁切；想保留整图就选“完整显示”。暗化、仅壁纸模糊与面板实度即时生效并自动保存，不打断当前试听。恢复默认不删除已导入副本。



速度、移调、和弦、轨道与循环仍在主演奏区的 **演奏调校** 中；Esc 可收起并恢复逻辑焦点。适配说明与谱子来源可展开；无音可演奏时自动展开原因。背景使用安全的深色遮罩和面板，不提供会让小字看不清的过低面板实度。



## 第一次在游戏内使用



1. 先在琴伴选择一首简短谱子，点 **本地试听**。试听为合成音，不是游戏原始采样；电脑实际扬声器输出未在自动化中听辨。

2. 查看适配统计和警告，调整速度 / 和弦 / 轨道，再试听。参数修改会停止当前播放，每首歌独立记住参数。

3. 在歌曲下方的乐器选择框选择要使用的乐器；进入原神，手动打开**同一乐器**的演奏界面，关闭聊天和菜单。软件不会帮你装备游戏道具。

4. 在琴伴“安全设置”刷新并选定窗口、勾选风险确认。只接受 `YuanShen.exe` / `GenshinImpact.exe` 可见窗口；不支持云原神或后台输入。

5. 点 **启用快捷演奏**，确认本次会话的窗口和授权。此操作每次启动只需一次；以后换歌曲或乐器无需再点开始。修改目标窗口或撤销风险确认会取消授权。

6. 选好歌曲和乐器，自行进入选定游戏前台，按 **Shift+Enter**，松开 **Shift 和 Enter** 即开始；没有五秒等待，也没有确认弹窗抢走游戏焦点。程序不自动播放下一首游戏曲谱。

7. **F8** 暂停 / 继续，**F9** 停止 / 取消待启动。失焦或其他修饰键会停止；改谱、改乐器、参数或进度也会中止当前/待启动播放。重新开始须再次主动按快捷键。

8. F9 或 Shift+Enter 被占用时，本次启动不能启用游戏输出；本地试听仍可用。请先手动关闭旧琴伴实例，避免旧版占用 F9。不自动关闭游戏或旧实例。



用户已确认旧 0.1.0 以管理员身份运行后游戏演奏成功。本版不同乐器、长按音尾与 Shift+Enter 的真实游戏结果尚待手动验收，自动验证不会向游戏发送按键。游戏与琴伴权限级别不一致可能阻止输入；你可按已验证方式**手动以管理员身份运行新版**，程序不自动提权，也不会绕过系统保护。



本地试听为合成音，不是游戏录音。等拍、缺少时值的谱无法凭空恢复原曲节奏；优先使用包含音符时值的 MIDI / notes JSON，TXT 显式标明 :2 / :0.5。仅有 time 的 songNotes 保留起音差异但缺失音长会提示。拨弦音尾由游戏采样决定；长按并不保证延长拨弦声音。同键快速重复、大和弦可能漏音，<45ms 会提示降速。



本程序不读取游戏内存、不注入进程、不绕过反作弊。普通键盘输入并不等于官方允许自动演奏，不能承诺零封禁风险。请自行核对适用区服规则，不要将测试通过理解为游戏官方许可。



## 文本谱格式



每个音默认一拍。连续字符逐个演奏，圆括号 / 方括号表示同拍和弦。`|` 不增加时间；`-`、`.`、`0` 为一拍休止。`:2` 两拍，`:0.5` 半拍，允许 1/16–32 拍。`:时值` 在连续字符后作用于每个音，建议需要不同时值时用空格分开。



键位谱：

```text

TITLE=我的第一首

AUTHOR=我

BPM=100

FORMAT=keys

A A G G H H G:2 | F F D D S S A:2

(ADG):2 - Q:2

```



数字简谱，中音 1=C4：

```text

TITLE=我的数字谱

BPM=100

FORMAT=numbered

1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2

(135):2 0 1':2 1,:2 #1 b3

```

`'` 升八度，`,` 降八度，`#1` / `b3` 升降半音。以 `//` 或 `# 注释文字` 开头的行是注释；以 `#1` 等开头的音符不是注释。谱头只支持 TITLE / AUTHOR / BPM / FORMAT。



## JSON

```json

{

  "version": 1,

  "title": "我的 JSON 谱",

  "author": "我",

  "bpm": 100,

  "lengthMs": 2000,

  "notes": [

    {"pitch": 60, "startMs": 0, "durationMs": 500, "track": 0, "velocity": 90},

    {"pitch": 64, "startMs": 600, "durationMs": 500, "track": 0, "velocity": 90}

  ]

}

```

音高为 MIDI 0–127，startMs / durationMs 为毫秒；lengthMs 可选，用于保留尾部休止。BPM 20–400。也识别单首 `songNotes` 键位 JSON，`Key0=Q`、`Key7=A`、`Key14=Z`，time 为毫秒、缺失音长时按 200ms 试听。会展示警告要求核对映射，不能保证光遇等不同键盘布局的 JSON 通用。多首数组须拆分，禁止静默只导入第一首。



输入上限：单文件 16MiB、100,000 音符、原谱 30 分钟，单音时长 0–60,000ms。慢速播放会相应延长总演奏时间。试听只生成前 10 分钟；音域适配为 C3–B5 的 21 个自然音，不是自动还原所有半音、踏板或钢琴动态。



## 内置内容与未做功能



30 份是传统 / 古典旋律的手工教学短编、原创短曲和练习，包括小星星、欢乐颂等主题片段。不是完整热门商业歌曲授权曲库，没有抓取或打包第三方谱站；每首有来源说明。可在 tools/builtin-manifest.json 查看清单。



本版没有：在线曲库同步、账户 / 云上传、PDF/图片 OCR、MP3 自动扒谱、手机端、特殊和弦乐器全面适配或后台窗口消息输入。联网歌曲版权、更多格式和乐器需要独立处理，不能把未实现入口冒充可用功能。



## 本地数据



- UserData/library.db：用户曲库索引、收藏、队列、每曲参数及歌单；旧 library.json 只作为复制迁移输入，保留不覆盖。

- UserData/scores：标准化谱；UserData/originals：原始文件副本，ID 与曲库条目对应。

- UserData/preferences.json：音量、队列连续试听、目标乐器和外观偏好。

- UserData/backgrounds：自定义图片的独立 PNG 副本；恢复默认不删除文件。

- UserData/preview：自动生成的试听 WAV。可在退出程序后由你手动清理缓存；程序不删除原始谱子。

- 内置 Songs 为只读来源，另存工坊新谱不会覆盖它们。导入失败会逐项报告，损坏曲库索引会拒绝启动并保留原文件，不自动清空修复。

- 请把程序完整解压到可写目录；只读目录会提示数据保存失败。



## 源码与构建



上游原目录仅作来源参考。请构建 QinBan.slnx / QinBan.Desktop，而不是 AutoMidiPlayer.sln / AutoMidiPlayer.WPF。需要 .NET 10 SDK；本工作区 SDK 位于父目录 .tools/dotnet，已校验微软发布的 SHA512，没有系统级安装。



```powershell

# 在此源码目录执行

.\build-qinban.ps1 -Mode build

.\build-qinban.ps1 -Mode test

.\build-qinban.ps1 -Mode publish

```

发布包含运行时，没有上传、提交或公开发布。LICENSE、QINBAN-NOTICES.md、licenses 目录包含 GPL / 依赖声明。源码压缩包包含匹配此版的新增源码、上游快照和构建脚本；不含用户数据、.git、SDK、NuGet 缓存或庞大测试临时文件；verification 只包含只读报告与界面证据。



## 验证证据



自动化使用记录器而非真实键盘；WPF 自测以 --ui-test 启动，在独立 --data-dir 中运行且拒绝真实游戏按键。--capture-only 用于冷启动截图。源码目录 .validation 保留测试报告与早期失败记录，验证摘要见 VALIDATION.md / design-qa.md；交付包中保留 verification 的报告与截图。可以用 tools/validate-portable.ps1 在新目录复验。一次 .NET CLI 首次初始化产生的用户级 localhost 开发证书及不能确认的 CLI 遥测状态，已在 VALIDATION.md 第 5 节披露，未擅自清理。



**本版通过本地构建和软件级验证；不把旧版管理员运行成功扩展为新版全部游戏功能已验收。**



## 0.2.0 节奏与来源乐器



- 内置生成器原来把短句最后的 :2 误用到整句。本版只让句尾音延长；小星星 96 BPM 的前六个四分音符 625ms，句尾两拍 1250ms。30 份内置教学谱已重新生成，不声称全部是原曲精确还原。

- TXT 时值现在完整写入 durationMs，连续串 ASD:2 仍保持旧含义：每个音两拍；需要不同时值时用空格分开。内置生成器短句简写与公开 TXT 语义不同，不混用。

- 来源是乐器键位谱时可用 INSTRUMENT=euphonia 等谱头；对应 JSON 可用 keyInstrumentId。详见 INSTRUMENTS.md。界面选择的是目标，不强改原谱音高。



## 旧数据与构建



新版默认使用新目录的 UserData，不覆盖或读取旧版目录；复制进新的数据目录后才自动执行一次 SQLite 迁移。需沿用收藏/导入谱时，先手动退出两个版本、备份旧 UserData，在首次启动且新版没有 library.db 时再将其**复制**到新版同名目录；不要移动或删除旧数据。已有 library.db 的目录不自动合并，详见 SCORE-LIBRARY.md。旧 options/countdownSeconds 字段兼容读取但不再使用倒计时。



构建入口 build-qinban.ps1 的 build / test / publish。publish 输出按版本独立目录；测试只用隔离数据和记录器。源码包包含生成器、测试、图标来源与 GPL/MIT/CC0 说明，不包含用户数据或巨型游戏资源导出。



## 0.4.2 大曲库底座（本地测试版）



只读 SQLite 内置目录、独立用户数据库、每页 50 谱目、中文/歌手/别名/拼音/首字母搜索、歌单管理、批量收藏、跨页切歌及局部事务保存已实现。保留原 UI、背景与 Shift+Enter 安全路径。原 30 教学谱字节未改，新增真实歌曲 0；100 黄金样本和 2 万真实歌尚未完成。



曲库与复制迁移：SCORE-LIBRARY.md；谱源/审核及真实素材阻塞：SOURCE-INTAKE.md；100 自制时序夹具和 20k/50k 元数据基准只作为工程证据。选谱目前为按需同步读取，压力下大谱 UI/真实游戏/断电与磁盘耗尽恢复尚未验证。
