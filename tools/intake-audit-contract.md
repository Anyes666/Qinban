# 入库行政证据审计合同（工具专用）

## 范围与兼容性

本工具只读本地源、reference、规范化谱和审校文件，只创建新报告。
EVIDENCE_COMPLETE 仅表示结构、字节绑定、范围声明与批内身份未发现冲突。
**不是歌曲数量认证、版权认证、真实人审认证、音乐完整性认证或游戏实测认证。**
不联网，不复制到 Songs，不删除源文件，不向游戏发送按键。空台账维持 0。

CSV 列和顺序不变，沿用 SOURCE-INTAKE.md。预算沿用应用和工具：
单文件 16 MiB、JSON 深度 32、批次最多 10,000 编配、最多 100,000 音、
总长最多 30 分钟、单音时值最多 60,000 ms、时序误差最多 0.0021 ms。
台账也采用 16 MiB 预算。超预算或全局格式错误使整批不能计为证据完整。
路径必须相对于 batch 根且解析后仍位于根内。所有输入只读，已有报告拒绝覆盖。

## 此次必须补齐的行政字段

以下只属于审计 sidecar，不修改应用、原 normalize 入口或全局审校模板：

- timing_report 增加 referenceFile（batch 根相对路径）；现有 referenceSha256
  必须绑定实际存在的 reference。sourceSha256、normalizedSha256 同样匹配实际字节。
  旧 normalize 已输出 referenceSha256，但未输出路径；应创建新的补充报告，
  不覆盖旧报告，不编造 PASS，不由工具猜测 reference 路径。
- 三份审校文件必须有 workId，精确匹配该行 work_id。music_review、game_review
  还必须有 editionId，精确匹配 edition_id。rights_review 可覆盖整个作品的编配权限；
  如提供 editionId，也必须匹配。不支持通配符或借用别的作品审校来凑数。
- music_review 增加 completeness: "full-work" 和 reviewedLengthMs。
  reviewedLengthMs 必须为有限正数，与规范化谱全长在时序容差内一致；谱同时对照 reference。
  这仅检查审校声明覆盖的范围，不能证明真实旋律或尾声完整。
- game_review 按原合同补齐非空 instrumentId、gameVersion 和对象型 playOptions。
  如 playOptions 包含 instrumentId，须匹配审校目标。参数内容、版本、听辨仍须真实人审。
- platform_ids 仍为字符串，多个稳定平台身份以分号分隔。身份必须非空且不重复，
  批内相同平台身份不能归到不同 work_id。

缺少上述字段的旧证据明确拒绝，不静默补全。
decision: approved、reviewer、reviewedAt（ISO 日期或时间）、notes 均只是人类声明。
rights_review 的 permissions 必须为列表并含 normalize、arrange、bundle，不代表许可证鉴定。

## 结构与实际绑定

规范化谱必须为实际导出的 version=1 notes 对象，不是 songNotes、数组或占位对象。
必须有有限正 lengthMs，覆盖所有音符并保留尾部休止。普通应用导入仍可使用原默认值；
本工具只对 full-work 规范化证据要求明确全长，不改变应用导入格式。
reference 必须为对象并含 notes 和有限正 lengthMs。

每个 note 必须是对象并具备 pitch、startMs、durationMs。
pitch 为整数 0–127；startMs 有限且 ≥ 0；durationMs 有限且 > 0、≤ 60,000 ms；
结束时间不得超过 30 分钟。布尔值不是数值。
track、velocity、percussion 仍可选，沿用 NoteEvent 默认值 0、90、false。
如提供则校验 track 整数 0–1023、velocity 整数 1–127、percussion 布尔类型。
不增加上述三个每音字段的必填要求。音符次序不影响比较。
可选元数据沿用应用默认值和长度限制，属性名大小写兼容应用。
keyInstrumentId、retrievedAt 如出现则验证应用现有乐器 ID 或 ISO 时间类型，不设为新必填项。
重复属性（含大小写变体）、非有限 JSON 数、超深嵌套、不合法 UTF-8 明确拒绝。

源支持本地 .mid、.midi 或 notes JSON。MIDI 使用现有独立 SMF 解析器；
JSON 按应用 version=1 notes 结构验证，保留源 JSON 的版本和长度默认导入行为。
源的实际音高、轨道、力度、打击乐、起音、时值、全长必须对照 reference。
规范化谱还须同时对照 reference 与实际源，不能用容差内的 reference 桥接超容差的两端。
核对报告 notes 与重新计算的 maxErrorMs，不把自声明 PASS 当作实际内容验证。
源、规范化谱、reference 均拒绝 synthetic=true 或非布尔 synthetic，缺省沿用 false。
规范化 provenance 保留 sourceSha256、timingStatus 绑定；非空 workId、editionId
如提供必须匹配台账，不强迫 normalize 默认的空身份字段变成应用新必填字段。

## 重复、异常、计数

重复 edition_id 拒绝所有冲突行。相同源字节、规范化字节、源或规范化的完整音符及
长度指纹、平台身份被声明为不同作品时，所有冲突行拒绝，不由行序决定作品身份。
同作品的相同源或规范化音符长度指纹只计首份，后续重复编配拒绝。
真正不同的编配只增加编配数，不增加不同作品数。指纹是精确数值比较，不是旋律识别；
不同字节、不同音乐内容的同名作品、错报平台身份、精心伪造的全套声明仍须人审。

报告保留 rows，并输出 rejectedRows、evidenceCompleteEditions、
evidenceCompleteDistinctWorks、fatalErrors。每行异常带阶段名和明确拒绝原因。
全局 CSV、读取、预算异常使已读行全部拒绝。CLI 遇拒绝或全局异常退出 1；
空表或无拒绝退出 0，不代表黄金样本已经完成。输出创建失败明确报错，不删除输入。

## 确定性测试

全部 fixture 为自制 SMF、JSON 字节及显式 test-only 审校占位字段，
不是歌曲、授权、证书或真实人审。synthetic=false 只用于测试行政分支。
不修改正式台账。设置 INTAKE_TEST_EVIDENCE_DIR 可在新的隔离目录保留夹具、
拒绝列表和输入前后哈希。工具始终不改写或删除输入；真实歌曲新增为 0。

## 0.4.2 正式谱的歌手与语言身份

- `provenance.artists` 是最多32个、非空、去重的歌手名称列表；保留旧 `artist` 为兼容回退，不能以 `author`（谱作者/编配者）替代歌手。
- `languageTags` 是最多16个、不重复的简单语言标签，语法为2–8 ASCII字母加可选1–8字母数字子标签；不是注册表、实际语言或歌手身份认证。`cmn`=国语、`yue`=粤语、`zh`=中文未细分、`en`/`ja`/`ko`等；`zxx`表示版本明确无语言内容，不因软件用乐器弹奏就自动给原歌标纯音乐。
- **正式规范化证据新增必填**：至少一位歌手（`artists`，或旧非空`artist`）、至少一个明确语言标签，不能包含`und`未知。没有信息的候选或个人谱仍可在应用中保存/试听，但不得当正式身份齐全的谱。
- `album`、`versionLabel` 为可选字符串，分别最多1000/256个 UTF-16 code units。原index没有这些信息时留空，不依据标题、中文字符或上传者自动补全。
- **新增身份字段的长度单位统一为 UTF-16 code units**，与 C# `string.Length` 一致，不是 Unicode 码点数，也不是 UTF-8 或 UTF-16 字节数。`artists` 的每个名称和 `languageTags` 的每个标签最多256个单位，`album` 最多1000个，`versionLabel` 最多256个；列表项数上限仍分别为32/16。有效 BMP 字符占1个单位，`U+20BB7` 等补充平面字符占2个单位，空字符串在可选字段中长度为0。
- UTF-16 边界回归：128个 `U+20BB7` 的歌手名称或版本标签恰为256个单位，接受；129个为258个单位，拒绝。500个该字符的专辑恰为1000个单位，接受；501个为1002个单位，拒绝。只统一上述新增字段，不改变旧 `artist`、`aliases` 等既有字段的校验规则。
- 原MIDI/JSON源未带歌手语种时仍可进行时序对照；规范化正式证据需由可核验元数据补充后重新计算哈希并重新绑定审核资料。语法齐全不认证实际歌手、语种或版本。
