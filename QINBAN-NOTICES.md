# 琴伴 QinBan：来源与许可

<!-- 2026-10-07-current-library-snapshot-v4 -->

## 2026-10-07 最新可核验快照：中文流行优先

source/runtime 曲库均为 **6332 条**，不是旧历史段落中的 6000 条。教学/试听 32、POP909 中文候选 901、midi_lyric_corpus 中文流行 220、callmeyyzx-midi 中文候选 7、CantopopCorpus 粤语候选 105、OpenScoreLieder 357、PDMX 196、MutopiaProject 414、BFDB 4100；距离 20000 还差 **13668 条**。

- 明确带 `zh` 标签的条目共 1128 条（POP909 901 + midi_lyric_corpus 220 + callmeyyzx-midi 7）；明确带 `yue` 的粤语条目 105 条；两首试听谱带 `cmn`。`zh` 与 `cmn` 仍是分组标签，不代替逐首普通话核验。
- 中文标签命中 1233 条（普通话/中文 1128 + 粤语 105），其中 280 条带透明的 `大众优先` 编辑标签；该标签不是抖音、酷狗或网易云实时榜单认证。
- BFDB 的 4100 条目前没有可靠语种标签；不能把未标注条目全部计作英文歌。后续不再用英文/古典来源填充中文主力指标。
- 曲谱的 `candidate-unverified`、`musicReview=not-reviewed`、`gameReview=not-tested`、`redistributionVerified=false` 状态保持不变；不把索引元数据或来源时序校验冒充版权、人工听辨或原神内验收。
- 曲库页默认进入“中文流行（推荐）”筛选并使用“中文流行优先”排序；“大众优先中文”只显示带有透明编辑标签的中文条目，切换“全部语言”才显示其他谱目；分页在 SQL 层完成，不把全库谱子读入内存重排。

本段是当前快照；下方 6000 条及更早段落保留为历史记录，不应当前数量。
## 2026-10-07 中文大众候选增量：原位新增 7 首

- 本批原位加入：《青花瓷》《稻香》《孤勇者》《刚好遇见你》《芒种》《热爱 105°C 的你》《杀死那个石家庄人》，P0=5，P1=2。
- 批次使用已有结构化 MIDI 流水线：7/7 源时序对照通过、九种旋律乐器 63 组映射通过，没有新建发行文件夹。
- 本批仍为 `candidate-unverified`：未完成逐首人工听辨、原神内逐曲验收或再分发权利确认。详细证据见 `.validation/callmeyyzx-chinese-batch-20261007/`。

- UI 会在曲库页直接显示“中文流行 / 大众中文精选 / 明确英文 / 语种未标注”摘要；“语种未标注”不等于英文，未标注条目不会进入中文主力筛选。
## 2026-10-07 原位更新与中文来源审计补充

- 已将中文优先批次原位更新到 `D:\原神弹琴脚本\dist\QinBan-0.4.2-smooth-scroll-win-x64`，没有新建生产版本文件夹；`UserData` 未修改，原有 6325 份谱面内容保持不变，仅新增 7 条。
- 发行包当前包含 `6332` 条 `entries`、`6332` 条 `search_index`，SQLite `integrity_check=ok`。搜索索引与旧条目保持不变，仅加入 7 条新谱。
- 中文流行默认筛选为 `1233` 条，严格“大众优先中文”筛选为 `280` 条；“全部”仍可访问全库，不把未标语种条目自动归为英文或中文。
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

本项目是独立的离线派生工作台，不是 Jed556 的 Auto MIDI Player 官方发行版，也不代表原神或米哈游官方。

## 上游
- AutoMidiPlayer: https://github.com/Jed556/AutoMidiPlayer
- 参考快照：d479e6ee89e520daaf34dbda6ff004a2ef3f0ef3
- 原作者：Jed556；原始项目作者 sabihoshi（GenshinLyreMidiPlayer）。
- QinBan.Core/GameMapping.cs 的键位、音域与八度折叠/移调逻辑改编自上游。上游原工程完整保留，未修改。
- 琴伴新增代码采用 GNU GPL v3.0（见 LICENSE）；分发派生版本时请遵守许可证。
- 未使用上游品牌图标作为本软件品牌；琴伴不包含上游账号、遥测、更新器、后台窗口消息输入或提权启动逻辑。

## 本版依赖
- Melanchall.DryWetMidi 8.0.3：MIDI 读写，MIT。https://github.com/melanchall/drywetmidi
- .NET / Windows Presentation Foundation：MIT。https://github.com/dotnet/wpf
- 系统字体不随包分发。
- 更多上游原工程依赖说明见 THIRD-PARTY-LICENSES.md，不代表琴伴编译包含它们。

## 内置谱
Songs 由 tools/generate_builtin.py 在本项目中生成；每首包含 source/description。传统旋律为本项目重新编写的教学短编，非转载第三方 MIDI；另含原创练习与原创短曲。它们不是热门商业歌曲库，不保证完整还原原曲。新增编配代码及新增谱 JSON 使用 CC0-1.0；对于传统旋律本身不主张新增专有权利。

## 0.2.0 乐器资料与游戏原图

- 乐器音高与和弦事实参考 Specy/genshin-music 一手实现/录音审计（上游仓库 MIT）；未复制该仓库代码、MP3 或界面品牌资产。研究快照与表格见 INSTRUMENTS.md。
- 道具名称和图标名参考 DimbreathBot/AnimeGameData 游戏资源导出，不将其视为官方发布清单。
- Assets/Instruments/*.png 是 HoYoverse 游戏原始道具图标/角色头像，通过 Enka 与 BWIKI 镜像获取，用于本地辨识；权利归原权利人，不是本项目 GPL 或 CC0 素材，不声称商业使用或公开再分发授权。
- 绮筵之鼓的游戏资源图标复用豪鼓图标；声线用真实角色头像但不是独立道具图标。跃律琴图标尚未取得，未冒用其他图标。
- 本次只生成用户工作区内的本地测试包，没有提交或公开发布。若日后公开分发，应先核对游戏素材与所用曲谱的适用权利和规则。
- 图标下载 URL、SHA256：tools/instrument-assets.json；便携包同名文件。


## 0.3.0 用户提供的背景素材

- Assets/Backgrounds/night.jpg、blue.jpg 来自用户在本次界面改进请求中提供的两张图片；只生成等比缩小、去除附带元数据的新副本。原始文件没有修改或上传。
- 原画作者及再分发权利未经核验，图片不属于本项目 GPL / CC0 授权范围；仅用于本次请求的本地个人界面，不声称公开再分发、商业使用或官方素材许可。若以后公开发布，请先更换为明确可分发的素材或取得适用授权。
- 本地图像选择功能不连接任何图片云服务；导入副本只保存在所选 UserData/backgrounds。系统字体图标来自 Windows Segoe MDL2 Assets，不随包重新分发字体文件。
- 像素尺寸、来源说明和 SHA256：tools/background-assets.json；便携包同名文件。本次没有提交、推送、公开发布或上传图片。


## 0.4.0 SQLite / 检索资料 / 谱源范围

- Microsoft.Data.Sqlite / Microsoft.Data.Sqlite.Core 10.0.12：MIT；精确来源仓库 LICENSE：licenses/Microsoft-Data-Sqlite-MIT.txt。
- SQLitePCLRaw.bundle_e_sqlite3 / core / lib.e_sqlite3 / provider.e_sqlite3 2.1.12：NuGet 元数据 Apache-2.0；附 licenses/SQLitePCLRaw-Apache-2.0.txt 与原 NOTICE.txt，其中包括底层 SQLite 的版权放弃声明。
- 离线拼音与简繁主变体使用 Unicode 17 Unihan；licenses/Unicode-License.txt 与 search-data-manifest.json 留存版本、来源、SHA256 和局限。上下文多音字并非本版能力。
- 依赖表达式取实际 restore 的 nuspec，原始许可取官方仓库标签/提交，哈希见 verification/0.4.0/dependency-license-sources.json。Raw 直连首次连接重置，后来通过官方 GitHub API取得许可；这不是歌曲采样。
- 旧 licenses/DotNET-MIT.txt 文件名沿用历史，实际内容是 SDK 附带的微软分发条款，不应把文件名当许可证鉴定；另附官方仓库 MIT 文本与第三方 notices。
- 上述0.4.0段落保留为历史快照；当前0.4.2工作区包含32条教学/试听、901条POP909、357条OpenScore Lieder、196条PDMX、414条Mutopia和700条BFDB候选，共2600条；其中2568条为结构化来源候选，不能据此称为平台热门全曲或完整原曲库。
- 合成压力元数据和自制时序夹具不随 Songs 发布；当前真实来源候选谱为2568条，仍按来源批次标记 source-compared 或结构转换证据，并保持 not-reviewed / not-tested / redistributionVerified=false，不能替代人工音乐、游戏和权利审校。
- 原游戏图标与用户背景的公开再分发权利仍未核验，只交付本地个人测试，不提交、推送或公开发布。

## POP909 100份本机来源谱增量

从music-x-lab/POP909-Dataset固定提交d83e6edba6872a704f5d3b8b32f5cb540088dae6取得100份真实MIDI并规范化，完整保留源音符的绝对时序与所有轨道；仓库MIT原文见licenses/POP909-repository-MIT.txt，README与来源哈希/索引见catalog-intake/pop100-2026-10-06。请保留Music X Lab及POP909 ISMIR2020论文作者归属。仓库许可不自动认证底层作品公开再分发；本次只用于用户本机个人曲库，不给予这些流行作品CC0/GPL许可。来源时序校验不等于音乐/全曲/游戏/权利认证。


## POP909本机曲库再次新增200份（2026-10-06）

本轮从已经留存的同一固定提交 `d83e6edba6872a704f5d3b8b32f5cb540088dae6` 归档提取200份真实源MIDI，未进行网络再下载，复用原100份的规范化方法。来源曲谱总计300份，另有原30教学和2用户试听试点，总曲库332条。原谱、许可与归属保留。
本轮原MIDI/索引/SHA256/完整200首清单及使用边界见 `D:\原神弹琴脚本\AutoMidiPlayer\catalog-intake\pop200-2026-10-06-v2`。仓库MIT不自动覆盖底层流行作品的公开再分发权利，仍只作为本机个人曲库；未上传、提交或公开发布。

## 2026-10-06 POP909剩余批次：新增601份本机来源谱

- 本批复用固定归档 `d83e6edba6872a704f5d3b8b32f5cb540088dae6`，从已收录300条之外选择601条真实MIDI，保留来源索引、MIDI哈希、规范化谱哈希和来源URL；不重复下载新的网络素材。
- 安装前曲库为332条，安装后源码 Songs 与 `dist/QinBan-0.4.2-two-song-pilot-win-x64/Songs` 均为933条。批次只新增601个谱文件并替换两个 catalog.db；EXE、UserData、原332条谱及既有非曲库文件哈希保持不变，没有新建发行目录。
- `WorkId` 表示作品归并，`EditionId` 表示具体来源/编配版本，`versionLabel` 用于显示 DJ版、新版、原版、影视/主题版本等。完整清单、版本组和拒绝项见 `catalog-intake/pop909-remaining-2026-10-06-v2`。
- 本批状态是 `source-compared / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。POP909仓库许可只说明仓库材料的许可边界，不自动授予底层商业歌曲的公开再分发权；当前交付仅作为用户本机个人曲库使用，不宣称可公开发布或商业分发。
- 真实安装与独立验证证据：`.validation/pop909-remaining-2026-10-06/delivery-report.json`、`update-installation.json`、`independent-installation-check.json`。该证据不等于逐首人工听辨、原神内逐首演奏或版权清权。


## 2026-10-06 BFDB v5 历史批次：追加 200条 ABC 转 MIDI 候选

- v5 实际 `selectedCount=200`，固定来源候选成员 `candidateMemberCount=13835`；唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=200`，`version-groups.json` 共200组且 `repeatedVersionGroups=0`。
- 失败记录663条：500条去重失败、163条转换/结构校验失败；失败记录留在 v5 acquisition report，不用占位或重复编配补数。
- 当前状态是 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。构建、预检、安装后、2600条完整性、UI 和冷启动证据只覆盖结构/时序与软件文件系统边界，未人工试听、未游戏测试、候选未清权；不证明候选曲目权利。
- 证据路径：`catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v5`、`.validation/bfdb-200-build-2026-10-06-v5`、`.validation/bfdb-200-independent-2026-10-06-v5.json`、`.validation/library-updates/bfdb-200-preflight-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v3.json`、`.validation/library-integrity-2600-2026-10-06-v1.json`、`.validation/portable-ui-2600-2026-10-06-v2`、`.validation/portable-cold-start-2600-2026-10-06-v1`、`.validation/portable-cold-start-runtime-2600-2026-10-06-v1`。

## 2026-10-06 BFDB v4 历史批次：追加 200条 ABC 转 MIDI 候选

- 本批实际 `selectedCount=200`，唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=200`，`version-groups.json` 共200组且本批无重复版本组；`WorkId` 归并作品，`EditionId` 区分具体来源/编配，`VersionLabel` 标记版本信息而不替代去重。
- 失败记录452条：300条重复 `EditionId`，152条转换/结构校验失败；候选仍为 `candidate-unverified`，不宣称热门歌曲覆盖；未人工试听、未游戏测试、候选未清权；不宣称公开再分发清权。
- 完整证据：`catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v4`、`.validation/bfdb-200-independent-2026-10-06-v4.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v2.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v2.json`、`.validation/library-integrity-2400-2026-10-06-v1.json`。

## 2026-10-06 BFDB v3 历史批次：追加 200条 ABC 转 MIDI 候选

- 来源为 Zenodo BFDB British Folk Database，记录 `14692025`，数据集声明许可证为 CC BY-NC 4.0；本批从固定本地归档的 13,835 个 ABC 成员中确定性扫描，使用本地 `music21 9.9.2` 转换并通过独立 `smf_reference.parse_smf` 校验 200 条。
- 本批唯一 `SourceSha256=200`、唯一 `EditionId=200`、唯一 `WorkId=197`；3 个 WorkId 组各有 2 个不同版本，使用 `VersionLabel` 标记。失败记录 240 条（100 条重复、140 条转换/结构校验失败）保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v3/acquisition-report.json`，未用占位谱凑数。
- 安装前曲库 2000 条，安装后源码 `Songs` 与既有 `QinBan-0.4.2-two-song-pilot-win-x64` 运行目录均为 2200 条；未修改 EXE、UserData、既有有效条目或发行目录结构。完整证据：`.validation/bfdb-200-independent-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v1.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v1.json`。
- 本批状态为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`；数据集许可证不自动清除底层曲目权利。

## 2026-10-06 BFDB 100条历史候选批次：ABC 转 MIDI


- 来源：Zenodo BFDB British Folk Database，记录 `14692025`，数据集声明许可证为 CC BY-NC 4.0；本地归档和 `dataset.csv` 的 SHA256 见 `D:\原神弹琴脚本\.tools\sources\bfdb-zenodo-14692025-2026-10-06`。
- 本批从 13,835 个 ABC 文件中确定性扫描，使用本地 music21 9.9.2 转换并通过独立 `smf_reference.parse_smf` 校验100条；115条转换/结构校验失败保留在 `catalog-intake/bfdb-2026-10-06/batch-100-2026-10-06-v2/acquisition-report.json`，没有用标题占位或修补坏谱凑数。
- 安装前曲库1900条，安装后源码与既有 `QinBan-0.4.2-two-song-pilot-win-x64` 运行目录均为2000条；未修改 EXE、UserData、原有曲谱或发行目录结构。批次的 `WorkId`、`EditionId`、`VersionLabel` 和原始 ABC/CSV 证据均保留。
- 本批只证明来源转换、SMF时序、九种旋律映射、智能衔接/软件级安装检查；人工听辨、原神内逐曲测试、底层民歌权利和 CC BY-NC 4.0 捆绑再分发范围仍未清权。不得将本批描述为两万首热门商业歌曲或可公开发布素材。
