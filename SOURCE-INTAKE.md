# 琴伴：P0 谱源准入与 100 首黄金样本

<!-- 2026-10-07-current-library-snapshot-v4 -->

## 2026-10-07 用户偏好纠偏：中文流行作为主力

按用户最新要求，曲库扩充策略从“可找到就凑数”改为“中文流行主力、大众优先、来源可追溯”：

- 后续新批次默认只接受普通话流行、粤语流行或有明确作品/作曲标记的中文歌曲；英文、古典、未标语种条目不再用来填充“中文流行”指标。
- 当前 4100 条 BFDB 全部是“未标语种”，不把它们统计为英文或中文；但也不再把它们放入默认中文主力视图。
- 待安装的 Anthology 200 首是中国民歌旋律候选，不是抖音/酷狗/网易云大众流行歌曲，本轮不安装，以免用民歌凑成流行数量。
- 已建立 `catalog-intake/chinese-pop-priority-2026-10-07-opencpop` 目标池：100 首普通话流行目标，其中 29 首按透明歌名优先集合标为 P0。这是候选目标清单，不包含谱文件，不计入内置数量。
- 抖音、酷狗、网易云榜单只用于建立候选顺序，不代替谱曲授权、改编权或内置再分发授权。

当前策略是：先把能合法取得、能核对歌手/版本、能做时值和原神乐器验证的中文流行批次，再扩量到 2 万。候选词、网页谱或未知权利的 MIDI 不能直接当作内置曲谱。

## 2026-10-08 新批次中文流行证据准入与复核

后续中文流行新增批次必须先运行 `tools/select_chinese_pop_batch.py`，遵循 `tools/chinese-pop-admission-policy.md`：本地 MIDI 哈希精确匹配；身份、权利与榜单的核验清单及其原始来源快照都必须有本地证据文件与 SHA256 绑定；逐曲授权同时允许改编和桌面软件再分发；近期抖音/酷狗/网易云官方榜单证据齐全；并满足近三年版本比例、歌手与 WorkId 多样性约束。此步骤是只读准入和排序，不代替音乐听辨或原神内测试。

- 当前只读预检输入为 332 条中文/粤语候选（midi_lyric_corpus 220、callmeyyzx-midi 7、CantopopCorpus 105）；均为当前曲库已存在的 EditionId，不能作为新增数量。候选清单中的旧 `productionBuiltin=false` 字段已过期，以当前 `Songs/catalog.db` 查询为准。
- 预检结果：332 输入、0 个满足完整身份/权利/热度证据门的候选；所有候选缺少逐曲改编+桌面再分发授权及官方热榜证据。另有一首缺歌手、7 首缺版本标签。227 个 midi_lyric_corpus/callmeyzx 候选来源哈希与当前曲库完全匹配；另外 105 个 Cantopop EditionId 已存在。候选仍保留，不删除、不回写其谱面或 metadata，权利状态在独立审计中按未知/未核验处理。
- 对固定的 midi_lyric_corpus commit `1837353ec30d3e9272dc585efb306176baf13da3` 核验了官方 GitHub API：仓库根目录为 `README.md` 与 `data`，无 LICENSE/COPYING，GitHub license endpoint 返回 404；README 介绍 MIDI/歌词语料及研究用途，但未给出歌曲数据授权。这只能说明未找到适用于歌曲/MIDI 的授权，不能推断已获再分发权。
- v4 的 `DRY-RUN-PASS` 记录 `applied=false`，该次 dry-run 本身没有安装；但同一 220 个来源哈希目前已由当前曲库独立核实存在，因此不能重复计数。
- 证据报告：`.validation/chinese-pop-admission-20261008/source-rights-audit-final.json`、`.validation/chinese-pop-admission-20261008/chinese-pop-priority-preflight-332-final.json`。早期字段映射错误的报告只保留为 `INVALID-*` 诊断，不作准入结论。
## 2026-10-08 中文热歌曲谱源准入与授权准备队列（未入库）

- 从 `catalog-intake/chinese-pop-chart-candidates-20261007-v1/candidate-batch.json` 复核到 50 个标题/艺人目标、59 条平台/榜单线索。19 个候选作品仅以规范化标题/别名匹配到 20 个既有条目，不能据此认定具体录音/编配版本相同；其余 31 个没有精确目录匹配。本批取得可安装结构化谱 0 首、逐曲改编授权 0 首、桌面离线再分发授权 0 首，可导入数 0。
- 已生成逐曲授权准备材料：`catalog-intake/chinese-pop-chart-candidates-20261007-v1/rights-clearance-queue-20261008.csv`、`rights-clearance-request-template-20261008.zh-CN.md`、`source-gate-findings-20261008.json` 和 `README-licensing-queue-20261008.md`。草案未发送、未联系权利方；榜单热度不能替代曲谱许可，所有候选均标记不可导入。
- 官方谱源审计结论：POP909 的仓库 MIT 标记未证明逐首底层作品可改编并桌面捆绑再分发；OpenCpop 官方许可为 CC BY-NC-ND 4.0 非商业下载，不能直接支持衍生 MIDI；CCMUSIC 限定签约大学研究访问；MIR-MLPop 是音频/歌词标注而非 playable MIDI，且限制商业使用。本轮在这些已查来源中未找到满足版本身份、可读曲谱、改编与桌面离线再分发的来源；不据此断言其他地方不存在可谈判授权。
- 抖音开放平台榜单 API 需 `data.external.billboard_music` 权限；普通歌单顺序不当作排名。队列区分酷狗排名线索、非排名列表、第三方镜像和用户指定曲目。
- 本轮无生产导入、无现有曲谱重标；source/runtime `Songs/catalog.db` SHA256 均为 `F3F8D410E644831DC85612C42398E3EE359AC97C78FC991DBD6CCFD2A371082D`，发行版 EXE SHA256 与本次审计基线一致；UserData 未访问。
## 2026-10-07 最新可核验快照：中文流行优先

source/runtime 曲库均为 **6332 条**，不是旧历史段落中的 6000 条。教学/试听 32、POP909 中文候选 901、midi_lyric_corpus 中文流行 220、callmeyyzx-midi 中文候选 7、CantopopCorpus 粤语候选 105、OpenScoreLieder 357、PDMX 196、MutopiaProject 414、BFDB 4100；距离 20000 还差 **13668 条**。

- 明确带 `zh` 标签的条目共 1128 条（POP909 901 + midi_lyric_corpus 220 + callmeyyzx-midi 7）；明确带 `yue` 的粤语条目 105 条；两首试听谱带 `cmn`。`zh` 与 `cmn` 仍是分组标签，不代替逐首普通话核验。
- 中文标签命中 1233 条（普通话/中文 1128 + 粤语 105），其中 280 条带透明的 `大众优先` 编辑标签；该标签不是抖音、酷狗或网易云实时榜单认证。
- BFDB 的 4100 条目前没有可靠语种标签；不能把未标注条目全部计作英文歌。后续不再用英文/古典来源填充中文主力指标。
- 曲谱的 `candidate-unverified`、`musicReview=not-reviewed`、`gameReview=not-tested`、`redistributionVerified=false` 状态保持不变；不把索引元数据或来源时序校验冒充版权、人工听辨或原神内验收。
- 曲库页默认进入“中文流行（推荐）”筛选，并使用“中文流行优先”排序：先显示大众优先，再显示其他中文流行候选；切换“全部语言”可查看完整曲库。“大众优先中文”只显示带有透明编辑标签的条目。分页在 SQL 层完成，不把全库谱子读入内存重排。

本段是当前快照；下方 6000 条及更早段落保留为历史记录，不应当前数量。
## 2026-10-07 中文大众候选增量：原位新增 7 首

- 本批原位加入：《青花瓷》《稻香》《孤勇者》《刚好遇见你》《芒种》《热爱 105°C 的你》《杀死那个石家庄人》，P0=5，P1=2。
- 批次使用已有结构化 MIDI 流水线：7/7 源时序对照通过、九种旋律乐器 63 组映射通过，没有新建发行文件夹。
- 本批仍为 `candidate-unverified`：未完成逐首人工听辨、原神内逐曲验收或再分发权利确认。详细证据见 `.validation/callmeyyzx-chinese-batch-20261007/`。

- UI 会在曲库页直接显示“中文流行 / 大众中文精选 / 明确英文 / 语种未标注”摘要；“语种未标注”不等于英文，未标注条目不会进入中文主力筛选。
- 新增“语种待核验”筛选查看未补齐语种标签的条目；不把它们归类为英文或中文。
- 批次安装的 `--language-policy` 仅是分批更新时的语种/标签硬门：`chinese-pop-first` 要求明确的中文/粤语流行语种和标签，`chinese-pop-main` 还要求含“大众优先”标签；`none` 跳过此门。该检查不核实授权、歌曲/版本身份、榜单热度、谱面质量或游戏内效果。
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

## 2026-10-06 后续扩充快照

当前源码和既有 two-song-pilot 运行目录均为 **2600 条**：32 条教学/试听、901 条 POP909、357 条 OpenScore Lieder、196 条 PDMX、414 条 MutopiaProject、700 条 BFDB ABC→MIDI 候选。BFDB v5 本批新增200条，完成独立源字节/时序检查、结构校验、add-only 原位安装和独立 post-install/完整性检查；本批唯一 `SourceSha256=200`、`EditionId=200`、`WorkId=200`，没有重复版本组。它们仍是 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`，未完成人工试听、原神内游戏测试或候选权利清权。

证据：`catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v5`、`.validation/bfdb-200-build-2026-10-06-v5`、`.validation/bfdb-200-independent-2026-10-06-v5.json`、`.validation/library-updates/bfdb-200-preflight-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v3.json`、`.validation/library-integrity-2600-2026-10-06-v1.json`、`.validation/portable-ui-2600-2026-10-06-v2`、`.validation/portable-cold-start-2600-2026-10-06-v1`、`.validation/portable-cold-start-runtime-2600-2026-10-06-v1`.

## 2026-10-05 历史状态（保留）

- 真实谱源新增 **0**；黄金样本 **0/100**；随包仍为原 30 份教学短编/练习。
- 本轮两次批量公开谱源采样相关指令被运行限制拒绝，均未执行；没有取得 MIDI，也没有落地采样脚本。不换通道绕过限制，不用生成曲、练习、歌名目录或重复编配补数量。
- 公开谱源的候选核查已在耐久计划记录。古典公开谱候选不能替代抖音/酷狗热门完整作品覆盖。平台身份、榜单/录音与可转换/编配/内置的曲谱来源分别留证；未购买任何素材或许可，未公开发布。
- 用户点名的《美人鱼》《日不落》及平台流行歌覆盖已记录为请求元数据（requested-coverage.json）；完整优先清单、可用试供素材、内置/编配范围及逐首音乐/游戏审校证据仍缺失。只有获得这类可核验资料后，才推进真实 100 首试点和数量扩张。

## 已提供的本地工作流

`catalog-intake/golden-samples.csv` 是空台账，不预填 100 个占位歌名。每个作品使用稳定 `WorkId`，每份来源/编配使用唯一 `EditionId`；`VersionLabel` 仅标注版本、来源或编配差异，不替代 `EditionId`/`SourceSha256` 去重。许可来源、完整性、原文件/规范化文件、时序与人工审校证据分别关联。多份编配不增加不同作品数量。

## 2026-10-06 BFDB v5 历史批次：200条准入记录

- 固定来源仍为本地 `D:\原神弹琴脚本\.tools\sourcesfdb-zenodo-14692025-2026-10-06`，候选成员 `13,835`；v5 实际 `selectedCount=200`。
- v5 失败记录 `663` 条：500条去重失败、163条转换或结构校验失败；失败项保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v5/acquisition-report.json`，不补占位。
- v5 唯一 `SourceSha256=200`、`EditionId=200`、`WorkId=200`，`version-groups.json` 为200组且 `repeatedVersionGroups=0`。`WorkId` 归并作品，`EditionId` 区分具体版本，`VersionLabel` 提供人可读版本说明。
- v5 的结构验证边界是来源转换、独立源字节/时序、数值/结构、add-only 文件系统和软件级报告；未人工试听、未游戏测试、候选未清权。状态保持 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。
- 验证路径：`.validation/bfdb-200-build-2026-10-06-v5`、`.validation/bfdb-200-independent-2026-10-06-v5.json`、`.validation/library-updates/bfdb-200-preflight-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v3.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v3.json`、`.validation/library-integrity-2600-2026-10-06-v1.json`、`.validation/portable-ui-2600-2026-10-06-v2`、`.validation/portable-cold-start-2600-2026-10-06-v1`、`.validation/portable-cold-start-runtime-2600-2026-10-06-v1`。

## 2026-10-06 BFDB v4 历史批次：200条准入记录

- 固定来源为本地 `D:\原神弹琴脚本\.tools\sourcesfdb-zenodo-14692025-2026-10-06`，13,835 个 ABC 成员；使用本地 `music21 9.9.2`，实际 `selectedCount=200`。
- v4 失败记录452条：300条 dedupe/重复 `EditionId`，152条 convert-or-validate 转换或结构校验失败。失败项保留在 `catalog-intake/bfdb-2026-10-06/batch-200-2026-10-06-v4/acquisition-report.json`，不补占位。
- v4 唯一 `SourceSha256=200`、`EditionId=200`、`WorkId=200`，`version-groups.json` 为200组且重复版本组为0。`WorkId` 归并作品，`EditionId` 区分具体版本，`VersionLabel` 提供人可读版本说明。
- 独立验证只覆盖来源字节/时序、结构化转换、软件级 add-only 安装和目录完整性；不等于人工试听、热门歌曲覆盖、原神内游戏测试或版权/捆绑再分发清权。状态保持 `candidate-unverified / musicReview=not-reviewed / gameReview=not-tested / redistributionVerified=false`。
- 验证路径：`.validation/bfdb-200-independent-2026-10-06-v4.json`、`.validation/library-updates/bfdb-200-apply-2026-10-06-v2.json`、`.validation/library-updates/bfdb-200-postinstall-2026-10-06-v2.json`、`.validation/library-integrity-2400-2026-10-06-v1.json`、`.validation/portable-ui-2400-2026-10-06-v1/ui-test-report.json`、`.validation/portable-cold-start-2400-2026-10-06-v1/cold-start-report.json`.

1. **覆盖和来源**：获得有明确使用范围的本地 MIDI/标准化 notes JSON。记录标题/作者/歌手/平台身份、谱源 URL、版本、源文件 SHA256。当前没有 MusicXML 导入、图片 OCR 或音频扒谱，不能把格式字段当已实现能力。
2. **源时序对照**：对 MIDI 使用 `tools/smf_reference.py` 的独立解析器生成参考 JSON，然后由 `QinBan.LibraryTools normalize` 比对音高、起音、时值、轨道、力度、打击乐标记和总时长。归一化后的谱与报告创建为新文件，拒绝覆盖。
3. **人工权利核验**：rights_review JSON 绑定源文件哈希；记录 reviewer、reviewedAt、decision、notes，及 normalize/arrange/bundle 的实际适用权限。填写 approved 不是自动获得权利，必须基于真实合同/许可依据。
4. **音乐核验**：music_review 绑定规范化文件哈希；逐首核对主旋律、拍子、长短音、休止、反复/尾声、声部与完整性。时序转换一致不等于源谱本身正确。黄金样本不以抽检替代逐首审校。
5. **目标乐器核验**：game_review 绑定规范化文件哈希，附 instrumentId、游戏版本/参数/听辨说明。记录移调、半音替换、音域折叠、删音及失真；人工监督实测，不让自动测试向游戏发键。
6. **台账审计**：`audit_score_intake.py` 只检查证据齐全/哈希绑定、完整作品声明、重复作品/文件计数和许可字段，拒绝缺证据与合成数据。它**不能自动证明合同有效、源谱准确或审校人真实**，也不会把候选拷入 Songs 或发布曲库。
7. 达到 100 个不同真实完整作品且复核通过后，另建许可与游戏素材范围明确的样本包，测实际单首大小/审校工时。当前包不能标“100 黄金歌曲已完成”或“2 万歌库”。

本地命令（源码目录；所有输出使用新路径）：

```powershell
# 已获准本地 MIDI 生成参考，不抓取网络
python -c "from pathlib import Path; import sys,json; sys.path.insert(0,'tools'); from smf_reference import parse_smf; Path('new-reference.json').open('x',encoding='utf-8').write(json.dumps(parse_smf(Path('source.mid').read_bytes())))"
# 比较与规范化；这一步不会标成人工/许可/游戏认证
..\.tools\dotnet\dotnet.exe run --project QinBan.LibraryTools -c Release -- normalize source.mid new-reference.json new-normalized.json new-timing-report.json
# 路径均相对于获准素材的 batch 根；保持输入只读
python tools\audit_score_intake.py catalog-intake\golden-samples.csv path-to-local-batch new-intake-audit.json
```

`review-template.json` 是待填写字段模板，不是审校证书。rights_review 的 sha256 使用原 MIDI；music_review/game_review 使用未再修改的规范化 JSON。任何改编/改时值都要生成新版本并重新绑定证据，不沿用旧哈希。

## 工程证据不是歌曲数量

- 100 个自制 SMF 时序测试覆盖 20 种确定性节奏与 5 组速度场景，包含附点、三连音、长短音、休止、多轨和弦、打击乐、跨变速长音和 EndOfTrack 结尾休止。独立有理数积分/SMF 解析/.NET 读取/JSON 往返对照，不是 100 首歌曲。
- 20k/50k 合成元数据测检索/分页/状态/实际 WPF，标记 synthetic，真实输入路径禁止合成测试谱。压力目录不随正式包安装。
- teaching-only `catalog` 工具仅允许 30 份原教学谱的已知 SHA256 集合，不能把任意用户或第三方谱自动赋予项目 CC0 许可。

## 下一步外部输入

需要用户提供可使用的 MIDI/结构化谱样本及许可/编配范围（也可提供合法试供方），并提供优先覆盖的实际歌曲清单。无需先买 2 万首；先以小批真实资料验证来源、全曲完整性与人工审校速率。对没有明确权利/质量依据的热门谱保持待审，不扩量凑数。

## 2026-10-05 来源调查与更严格审计

- 公开一手可行性报告：catalog-intake/source-feasibility-2026-10-05.md。调查已定位 POP909 的蔡依林《日不落》候选目录及多个《美人鱼》作品身份，没有获取音乐正文。PDMX、Mutopia、OpenScore 等候选数量不是已取得、已去重或已精校的作品数，不能相加凑目标。requested-coverage.json 只记录覆盖请求，不算入库谱。
- 0.4.1 准入工具增加实际规范化 notes 结构/finite 时值校验、独立 reference 与 timing_report 哈希绑定、作品/版本身份一致、全曲长度声明及目标乐器/游戏参数证据。边界与必填字段以 tools/intake-audit-contract.md 为准。
- 验证坏 JSON、缺音符字段、非有限数、哈希或身份不匹配不会通过；某行坏证据不崩溃整批。自动工具仍只输出行政证据齐全，不能认证审核人、合同或“听起来正确”。没有真实 100 首逐首听辨结果。

**解除素材门槛所需的实际输入：** 提供获准使用的本地 MIDI/标准 notes JSON，及针对转换、适配/编配、随离线软件内置用途的可核验范围说明；可先提供 10–100 首试供文件，不必先采购 20,000 首。不要提供账号密码。若仅有歌名、音频链接、截图或研究数据集总数，不能据此完成真实歌库。

## 0.4.2 主动发现与元数据边界

已主动取得原作者POP909 index.xlsx标题/歌手索引，按官方Git blob SHA与本地SHA256核对；离线解析909行，并留下抓取回执、候选JSON/CSV和指定标题匹配报告。source-index编号是候选身份，不是核验后的作品/录音ID。源未给语言/专辑，不推断填充。

候选在catalog-intake/discovery/2026-10-05-pop909，**没有下载MIDI、音频或乐谱正文，没有绕过此前受限批量采样，正式实际新增0**。候选不装入可播放库，不作为已取得黄金样本或当前平台热榜覆盖。对全网“所有流行歌”没有总量/日期/平台边界可验证，目标不以标题数量替代20000不同完整作品。

正式谱的normalized metadata需含歌手（artists或legacy artist）和明确languageTags（不能und）；新缺字段与坏字段在行政准入拒绝并明示。已有个人/教学缺字段在应用仍兼容。要继续真实收录，仍需要可获取的、适用内置用途且可作音乐对照的实际谱文件及审核资料，不擅自付款或登录用户账号。


## 2026-10-05 后续实物采集：不再仅有目录

这是 0.4.2 工程版交付后的独立采集批次，不追改当时“实际新增 0”的历史回执。助手自行取得 Mutopia 两份来源逐件声明 Public Domain 的 MIDI 及对应 LilyPond 源文件：Greensleeves 手风琴简编、Nº. 31. Auld Lang Syne. 古典吉他编配；4 个原文件共 16,713 字节。可导入 notes JSON、SHA256、原始页面和时序报告均在 catalog-intake/public-score-pilot-2026-10-05。

- 两份转换与独立原 MIDI 的起音/音长等对照通过，最大误差分别 0 ms 和 0.00075 ms；保留变化音长，不改为等间隔键位串。
- 隔离导入/检索/重启及 18 组乐器映射（23 个移调候选/组）通过 53 个断言。映射数值评分不是音乐/游戏验收，未打开实际 UserData，没有真实按键或音频输出。
- 完整性未知：Greensleeves 为特定简编；Auld Lang Syne 源 MIDI 没展开纸面反复，保留警告。供方 Public Domain 声明、解析通过不自动成为权利/音乐/游戏审校。
- 真实 MIDI 实际取得 **2 份**，可导入待审谱 **2 份**；现代流行谱正文 **0**，正式内置新增 **0**，黄金样本 **0/100**。原软件 Songs 和所有旧包未修改。
- 歌手/语种/专辑缺依据保持未知，不把谱维护者当歌手；暂存样本不满足正式热门曲元数据准入条件。
- 《日不落》《美人鱼》等入口核查见该批 modern-source-review.md，仅为候选，没有宣称已下载。没有绕过访问门槛、此前拒绝的批量操作，也没有付款或登录。

**责任调整：助手主动寻找与小批采集，不再把用户先提供 100 首素材作为搜索前提。** 100 首真实黄金样本仍是质量阶段门槛，而不是本批已完成数量；现代热门供谱、全曲与音乐审校、实际游戏验收仍待完成，不能用公开传统简编替代指定热门覆盖。

最终核验：独立导入/映射复测53项通过；哈希、MIDI参考重读、时序与分类绑定等551项保护断言通过，0失败。原30教学谱及0.4.0–0.4.2的9个发行物哈希不变，411个生产/上游文件与0.4.2源码ZIP一致。见该批validation/final-integrity-report.json；未重跑旧版完整UI/发布测试，因为本批没有生产行为变更。


## 2026-10-05 两首现代歌曲个人试听实物（独立包，非正式扩量）

用户本轮明确只先听蔡依林《日不落》及林俊杰《美人鱼》，满意后再提炼扩量。本批已自行取得EveryonePiano普通公开简谱阅读器的3页/2页谱面，AI辅助逐小节转写并新写独立稀疏伴奏，实际生成2份可播放notes JSON，新增个人试听内置2份；不是仅有歌名/候选。源图只在本机分析，未把原图、歌词、原唱音频打入新包，也未下载需VIP的MIDI或登录付款。

日不落126 BPM，70书面小节按反复/结尾/D.S./Coda展开116小节，约3分41秒；最终v2修正4处读谱问题。美人鱼96 BPM，36小节90秒源谱21音简编，不称原唱全曲，源谱首小节八度疑点待听辨。两首歌手、国语标签、专辑特务J/第二天堂、编配版本、来源和警告分开记录；谱维护者不是歌手。主声部/和弦为轨道1，新增稀疏伴奏轨道2可关闭。

- 最终曲谱与输入/来源回执：catalog-intake/two-song-listening-pilot-2026-10-05/compiled-reviewed及该批README。
- 独立软件包：D:\原神弹琴脚本\dist\QinBan-0.4.2-two-song-pilot-win-x64，32条=原30教学+2真实来源待校对试听，不改原Songs/旧包/真实UserData。
- 制库/独立重启235项、18组默认旋律乐器映射、8份WAV、修稿21项、最终EXE基线WPF68项及专项39项全通过；测试全程无真实按键，WPF试听静音。3鼓类仍安全禁用。数值映射、软件合成试听、自动测试不是逐首音乐认证。
- 来源声明为网友兴趣编配、个人学习/非商业；没有核验底层歌曲或公开软件再分发权利，不能把程序GPL/原30CC0许可自动盖到这两首。仅本机个人试听，不公开商业发行。
- synthetic=false、musicReview=not-reviewed、gameReview=not-tested、redistributionVerified=false；新增正式/黄金仍0。真实流行谱“个人试听内置2”与正式内置/黄金状态不得混计。未开始两万首扩量；用户听辨及真实游戏结果仍待验收。

历史0.4.2“现代正文0”的记录是当时快照，本节是后续取得与独立试点，不追改历史回执。

## 100份POP909真实源谱新增实物

本批主动采集并筛选100份MIDI，剔除98短片段与511冲突tempo；来源/版本/哈希和独立SMF参考在catalog-intake/pop100-2026-10-06。规范化谱已加入源码Songs与用户现有two-song-pilot目录，不再另建发行目录。逐音对照171445音符最大约0.001ms、900旋律计划、300鼓阻止、随机5首45调度器片段通过。100条为来源时序校验的个人内置，musicReview=not-reviewed/gameReview=not-tested/redistributionVerified=false/completeness=unknown，不转记为100黄金样本或20k正式歌库。旧两首用户反馈不自动覆盖新100的音乐和游戏状态。

## 2026-10-08 增量来源复核：独立中文流行线索

- 本轮复核新增发现 Pixabay 创作者 shanghaistoneman 的《一念千年》“国风版”和“热舞版”两个页面线索；可作为可能的版本组，但 WorkId/旋律同一性尚未确认。页面提供 MP3，未取得结构化谱，也未核验其是否为抖音/酷狗/网易云热歌。
- Pixabay 官方条款允许素材用于新创作，但禁止 standalone 内容分发。该软件若以单独可选曲谱形式分发其旋律转写，是否仍属于 standalone musical-content distribution 目前无法仅凭公开条款确认；因此该线索保持 `HOLD_LICENSE_SCOPE_AND_CHART_STATUS`，没有下载、转写或安装。
- 本轮新增可入库中文流行谱 0 首；`Songs/catalog.db` 只读快照为 6,332 entries、6,332 search-index rows，`quick_check=ok`。生产 Songs、发行 EXE、UserData 均未修改/访问。
- 增量证据：`catalog-intake/chinese-pop-source-audit-20261008-v2/`。同目录另记录 Figshare 传统中国 MIDI 线索；因不是中文流行且未检查具体作品，本轮不计数。

## 2026-10-08 酷狗 TOP500 中文目标池

- 依据酷狗 TOP500 页面 2026-10-07 的公开榜单快照，整理 22 条中文/华语目标，用于补充中文流行优先顺序；其中 20 条在当前 6,332 条目录中没有标题文本命中，2 条仅有标题文本匹配，不能据此确认具体录音/编配版本相同。
- 本批取得结构化谱 0 首、权利清除 0 首、生产新增 0 首。榜单排名只用于排序，不能替代 MIDI/谱文件、改编授权或桌面软件离线再分发授权。
- 证据与清单：`catalog-intake/chinese-pop-chart-candidates-20261008-kugou-v1/`；`candidate-batch.json` 绑定榜单提取文件 SHA256。现有曲库仍保持 6,332 条。

## 2026-10-08 OpenGufeng 隔离结构化候选

- 从公开仓库取得 8 个小型 MIDI 文件：4 个速度设置（72/108/128/156 BPM）× 旋律/和弦两类，统一归到 1 个 `WorkId`，用 8 个 `EditionId` 标记速度/轨道变体；避免把版本变体冒充 8 首作品。
- 8/8 通过本地 MIDI→规范谱转换与独立源时序对照，音符数合计 33,404，最大时序误差约 0.000998 ms；这些是结构/时序证据，不是音乐审校、热门身份、权利或原神游戏验收。
- 仓库有 MIT LICENSE，但许可证未专门说明 MIDI 数据文件范围；该批没有具体歌名、歌手、发行版本或平台榜单证据，`redistributionVerified=false`，因此只保留隔离候选，不复制到 Songs、不修改发行 EXE/UserData，也不计入中文流行/20,000 正式数量。
- 批次目录：`catalog-intake/opengufeng-20261008/`；manifest、原始 MIDI、独立 reference、normalized 谱和 timing reports 均有 SHA256 绑定。
## 2026-10-08 中文流行主力纠偏与曲库方向复核

用户明确要求：后续扩充的主力应是普通话/粤语大众流行，优先抖音、酷狗、网易云等平台热歌，不要再用大量英文或未标语种的曲目凑中文数量。本次完成只读方向复核，生产新增 **0 首**，没有修改 Songs、运行目录、EXE 或 UserData。

- source/runtime 曲库均为 **6,332 条**，`catalog.db` `quick_check=ok`，`entries=6,332`、`search_index=6,332`；明确标签为 `zh=1,128`、`yue=105`、`cmn=2`。中文/粤语筛选实际为 **1,233 条**，`大众优先` 编辑标签 **280 条**；该编辑标签不是平台实时榜单认证。
- BFDB **4,100 条**没有可靠语种标签（显式语言标签为 0）。英文式标题不能单独证明为英文，但这些条目也不再作为中文流行目标的新增吞吐；既有条目保持原状，不批量改标、不删除。
- 对酷狗 TOP500 的 2026-10-07 本地快照复核了 22 个中文/华语目标；规范化歌名+歌手只有《泪海》（许茹芸）和《情歌》（梁静茹）命中现有条目。命中条目均是 POP909 来源版，不能证明是榜单对应录音/编配版本，且 `redistributionVerified=false`、`musicReview=not-reviewed`；所以不重复计数，也不把命中当作新热歌版本。
- 已审计的来源中，现有中文谱、midi_lyric_corpus、CantopopCorpus、callmeyyzx-midi 均已在库内；`wyhlovecpp/Chinese-Songs-Midi-Dataset` 没有可直接取得的谱文件且标注学习/参考用途；`OpenGufeng` 只有未命名国风器乐研究候选。它们都不能在本轮合法、准确地新增主流中文热歌。
- 后续流水线改为：**平台热度候选池 → 歌名/歌手/作品与版本核验 → 取得完整 MIDI/MusicXML 或权利方明确允许改编及桌面离线捆绑的谱 → 规范化与独立时序校验 → 多乐器适配 → 软件试听与隔离回归 → 只有通过来源门槛的条目才原位 apply**。不同演唱/编曲/速度共用 `WorkId`、分别使用 `EditionId` 与 `VersionLabel`。

本次详细证据与哈希清单：`catalog-intake/chinese-pop-direction-20261008-v1/audit.json`、`README.md`。方向复核报告记录 `newProductionEntries=0`，不是 0 首中文候选，而是本轮没有足够证据把候选安全变成新的生产曲谱。
