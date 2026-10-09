# Pop100GapProbe（只读诊断）

授权写入范围仅本目录与 `.validation/pop100-gap-diagnosis-2026-10-06/mapping-*` 文件。生产 Core/Tests 项目只读引用，构建输出全部隔离；不要使用生产 bin/obj 或真实 UserData。

## 实现

- `Program.cs`：catalog只读Options加载、100×9对比、3鼓空输出、绝对时序/来源/时长/选项不变断言、自测、未播放WAV截片。
- `Metrics.cs`：SoundMs区间并集、单列首尾休止、起音gap、原轨和新增映射轨2 overlap、同拍/并发密度、key-onset差分。
- `FocusedCommands.cs`：`--focused-alltracks` 仅035/038×9的[1,2,3]；`--key-onset-changes` 436次原key-onset替换归因及隔离原生和弦反事实。
- `Build-Probe.ps1`：参考已有Pop100Tool；本地NuGet feed，不允许网络fallback；`--artifacts-path`重定向Core/Tests产物。`-IncludeCoreTests`编译未修改测试。
- `Report.py`：独立Python核验、CSV与报告生成，拒绝覆盖已有mapping报告。已有结果生成后再次执行会因文件存在而拒绝写入，这是有意保护。

## 当前权威结果

- `.validation/pop100-gap-diagnosis-2026-10-06/mapping-report.md`
- `mapping-results-verified.json`（900矩阵，修正sustainShortened口径）
- `mapping-focused-alltracks-verified.json`（18重点全轨，修正sustainShortened口径）
- `mapping-validation.json`（独立核验与保护证据）

先前JSON均保留不覆盖；初版sustainShortened把不同音长身份候选误计为截短，不能用该字段作结论。其静音/起音/密度/retention经重跑一致；回归自测136断言。

现有Core测试在132首曲库157/159（硬编码30与31不匹配）；从指定原30快照复制的baseline30-repo，同一未修改Tests DLL复跑159/159。两个结果都保留。

所有WAV仅由PreviewAudio生成，不播放。本probe不调用PlaybackEngine、系统输入或真实用户路径。现有Core测试只使用本工具内临时fixture和记录器。
