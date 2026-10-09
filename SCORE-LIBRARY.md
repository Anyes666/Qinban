# 琴伴 0.4.2：曲库与迁移

<!-- 2026-10-07-current-library-snapshot-v4 -->

## 2026-10-07 最新可核验快照：中文流行优先

source/runtime 曲库均为 **6332 条**，不是旧历史段落中的 6000 条。教学/试听 32、POP909 中文候选 901、midi_lyric_corpus 中文流行 220、callmeyyzx-midi 中文候选 7、CantopopCorpus 粤语候选 105、OpenScoreLieder 357、PDMX 196、MutopiaProject 414、BFDB 4100；距离 20000 还差 **13668 条**。

- 明确带 `zh` 标签的条目共 1128 条（POP909 901 + midi_lyric_corpus 220 + callmeyyzx-midi 7）；明确带 `yue` 的粤语条目 105 条；两首试听谱带 `cmn`。`zh` 与 `cmn` 仍是分组标签，不代替逐首普通话核验。
- 中文标签命中 1233 条（普通话/中文 1128 + 粤语 105），其中 280 条带透明的 `大众优先` 编辑标签；该标签不是抖音、酷狗或网易云实时榜单认证。
- BFDB 的 4100 条目前没有可靠语种标签；不能把未标注条目全部计作英文歌。后续不再用英文/古典来源填充中文主力指标。
- 曲谱的 `candidate-unverified`、`musicReview=not-reviewed`、`gameReview=not-tested`、`redistributionVerified=false` 状态保持不变；不把索引元数据或来源时序校验冒充版权、人工听辨或原神内验收。
- 曲库页默认进入“中文大众主力（推荐）”筛选，并使用“中文流行优先”排序：先显示编辑精选的大众中文条目；切换“中文流行候选”可查看完整中文/粤语候选，切换“全部”可查看完整曲库。分页在 SQL 层完成，不把全库谱子读入内存重排。

本段是当前快照；下方 6000 条及更早段落保留为历史记录，不应当前数量。
## 2026-10-07 中文大众候选增量：原位新增 7 首

- 本批原位加入：《青花瓷》《稻香》《孤勇者》《刚好遇见你》《芒种》《热爱 105°C 的你》《杀死那个石家庄人》，P0=5，P1=2。
- 批次使用已有结构化 MIDI 流水线：7/7 源时序对照通过、九种旋律乐器 63 组映射通过，没有新建发行文件夹。
- 本批仍为 `candidate-unverified`：未完成逐首人工听辨、原神内逐曲验收或再分发权利确认。详细证据见 `.validation/callmeyyzx-chinese-batch-20261007/`。

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

## 交付范围

这是 **P1 曲库底座的本地测试版**，不是已经收录 2 万首热门歌曲的版本。当前源码/既有运行目录为2600条：32条教学/试听与2568条结构化来源候选（901 POP909、357 OpenScore Lieder、196 PDMX、414 Mutopia、700 BFDB ABC→MIDI）；其中正式人工黄金样本 **0/100**，来源候选仍不等于原曲精确还原。20,000 / 50,000 条合成元数据只用于规模测试，100 个自制时序案例只用于转换回归，均不装入发布曲库、不计人工黄金样本数量。

## 2026-10-06 历史 2600 条来源台账（BFDB v5）

- 当前构成为：32 条教学/试听、901 条 POP909、357 条 OpenScore Lieder、196 条 PDMX、414 条 MutopiaProject、700 条 BFDB ABC→MIDI 候选；当前正式人工黄金样本仍为 `0/100`。
- BFDB v5 批次为 200 条：固定本地归档 13,835 个 ABC 成员，`selectedCount=200`，唯一 `SourceSha256=200`、`EditionId=200`、`WorkId=200`；失败663条（500条去重失败、163条转换/结构校验失败）保留在 acquisition report，不用占位或重复编配补数。
- `WorkId` 表示归并后的作品身份；同一作品的不同来源、编配或版本各保留独立 `EditionId`；`VersionLabel` 用于显示/解释版本，不替代 `EditionId` 或 `SourceSha256` 去重。版本数量不直接等同于不同作品数量。
- 当前 BFDB v5 仍为 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。已完成的是来源转换、结构/时序和软件级文件系统验证；未人工试听、未游戏测试、候选未清权；不构成热门歌曲覆盖证明或底层作品/捆绑再分发清权。
- 证据路径：`catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v5`、`.validation/bfdb-200-build-2026-10-06-v5`、`.validation/bfdb-200-independent-2026-10-06-v5.json`、`.validation/library-updates/bfdb-200-preflight-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v3.json`、`.validation/library-integrity-2600-2026-10-06-v1.json`、`.validation/portable-ui-2600-2026-10-06-v2`、`.validation/portable-cold-start-2600-2026-10-06-v1`、`.validation/portable-cold-start-runtime-2600-2026-10-06-v1`.

## 曲库使用

- 默认每页 50 份谱目，列表使用回收式虚拟化，上一页/下一页在曲库面板底部；播放器上一首/下一首能跨分页。
- 搜索支持中文一字/二字、歌手/作者、别名、简繁主变体、拼音、首字母；空格分隔的词同时匹配。优先排列标题精确与前缀命中，支持添加顺序、标题、时长排序及最近播放。
- 输入后 150ms 防抖，在后台线程查询。新查询会废弃旧结果，页面每次只取得当页元数据。最多 512 字/16 个不同词，超出会明示错误，不静默截断。
- 拼音采用 Unicode 17 Unihan 主读音，**不是上下文多音字识别**；多音字/特殊艺名由供谱者提供别名补正。标题拼音排序不是专门的地区词典顺序。人工标注相关性数据集尚未取得。
- “筛选 / 歌单”展开质量筛选与歌单管理。新建、改名、删除歌单；Ctrl/Shift 多选后加入歌单、移出所选、收藏所选。没有列表多选时，加入操作可使用右侧当前谱。
- 歌单去重并保留加入顺序。删除歌单/移出歌单只修改关系，不删除谱文件、原文件或收藏。收藏、播放队列、播放参数和最近播放独立于内置目录。
- 教学谱、来源时序校验、未人工精校、个人自声明分别显示。个人谱上的许可/审核声明不作为认证；仅凭供谱者名字不显示“时序校验”。本版没有人工精校正式歌库。
- 选定谱子时才校验资源哈希并读取谱；选谱的文件读取/音高时序适配在单飞后台任务中完成；快速切曲、改参数、换乐器只让最后请求应用，准备过程中禁用播放。文件解析不被强行终止，但解析后会检查取消并丢弃结果。热键不读文件，不会等待未就绪谱后自动开播；加载失败会清空旧就绪计划并禁用演奏。

## 存储与安全

- `Songs/catalog.db`：内置元数据/检索索引，连接以只读模式附加。运行时不将收藏等写入内置目录。
- `UserData/library.db`：用户谱索引、用户状态、歌单、迁移标记。局部参数与批量状态使用事务，不重写全库 JSON。
- `UserData/scores` 与 `originals`：规范化谱与原输入的独立副本；原输入哈希和规范化资源哈希分别记录。
- `preferences.json`、`backgrounds`、`preview` 的用途不变。程序不上传数据、不自动提权、不读取游戏内存。合成压力条目禁止真实游戏输出。
- 损坏 JSON/DB/资源哈希异常会明确报告，原文件不清空、不自动替换。SQLite 事务和回归测试不等于已通过断电、磁盘耗尽或所有杀进程场景。

## 从 0.3.0 沿用曲库（务必先看）

1. 手动退出两个版本，备份旧版整个 `UserData`。不要只复制 `library.json`，也不要移动/删除原目录。
2. **在第一次启动 0.4.0 之前**，把旧版整个 `UserData` 复制到 0.4.0 程序旁的 `UserData`，确认这里尚无 `library.db`。
3. 启动 0.4.0：一次性复制迁移旧 JSON，保存 `.pre-sqlite-*.bak` 副本；原 JSON、谱子、图片不覆盖。保留 ID、收藏、队列、最近播放与每曲参数。旧内置条目不再存在时放入 `retired_legacy`，不静默丢弃。
4. 查看界面迁移提示；有缺失资源/坏索引时先检查备份，不能把“保留元数据”理解为缺失谱已经修复。
5. 回退时运行旧版和它的原 `UserData`。0.4.0 的新收藏/歌单**不会自动回写旧 JSON**。

如果新版已经启动并有 `library.db`，**本版不做自动合并**。不要覆盖已有库，也不要仅把旧 JSON 复制过去后期待二次迁移。可使用新的、未启动目录进行复制迁移，或后续单独实现受测试保护的合并。

## 验证边界

20k/50k 是合成元数据 API 与实际 WPF 交互测试，不是实际 2 万首媒体资源包；数据库约 56/141 MiB，不包含 2 万/5 万首歌曲的谱文件体积。报告中的 `SongReads` 是成功 LoadSong 解析次数，不是底层文件句柄/系统磁盘读次数。100k 音符谱的 UI 阻塞、压力下调度抖动、断电/磁盘耗尽恢复及人工游戏体验未验收。正式素材扩量见《谱源准入》。

## 0.4.1 大谱补充

- 10k/100k 音符是自制隔离夹具，用于后台准备、取消、快速变更、坏谱和时间轴显示，不代表真实歌曲或逐首听辨。
- 极密同键、同色且屏幕上已重叠的音符矩形合并显示，避免数千个重复 WPF 几何体占用渲染资源；原谱、音符起音/时值和演奏事件不合并、不减少。
- 本版软件通过不代表热门歌已取得，更不代表两万首曲谱的音准已审核。谱源研究与审批资料在 SOURCE-INTAKE.md / catalog-intake 中。

## 0.4.2 歌手、语言、专辑与版本

新字段跟随每个谱版本持久化；无需改变SQLite表结构，检索索引包含歌手列表、原语言标签与中文标签、专辑和版本。不得把作者改成歌手或把目录标题当完整谱。
旧谱缺字段保留未知；个人谱导入/重启、旧Artist回退、多语种/多歌手JSON与TXT往返分别回归。正式声明计数还要求歌手和明确语种齐全，普通未知谱不因此拒绝导入。
未使用实际平台榜单给候选打“当前热榜”标签；909候选仅来源索引，实际曲谱取得和正式新增仍0。

### 0.4.2 既有个人 SQLite 检索升级

新版打开已存在的 schema=1 个人索引时，会一次性事务重建派生检索文本（search_semantics=0.4.2），使语种未知/新增身份词与新导入条目一致。逐条校验、两遍流式处理，不加载音符文件，不替换 metadata_json，不改收藏/队列/歌单；检索列或标记写入失败整体回滚并报错，坏索引不清空。重启不重复写入。

本地交付仍是独立目录，不自动找到或合并旧包 UserData；测试只用隔离目录。旧只读内置 catalog.db 不会自动改写，新版随包目录已重建；手工指定旧内置目录可能保留旧检索语义。首次大量个人条目升级耗时与全设备故障场景未验证。

## 100首原目录增量

当前132条。读取/检索仍使用只读catalog.db+所选曲谱，用户收藏/选项/歌单仍在独立UserData。100新谱默认MELODY，BRIDGE/PIANO可选，未猜语种。更新器tools/update_builtin_library.py先逐文件/索引验证、备份，add-only复制新谱并原子替换catalog；支持保留只读属性、失败回退和验证原备份后的重试。不是清空UserData迁移。当前工具针对本批132条，不宣称已具备任意20k素材的无人审校扩量能力。详见本批README。
