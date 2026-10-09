# SmartInterludeProbe（隔离离线sidecar）

只写此新目录与 `.validation/smart-interludes-2026-10-06` 的新 `matrix-*` 文件。主入口 public GameMapping.Build；Checks以线性选音/笛卡尔区间交集独立oracle检查raw>=3s资格、physical/arpeggio/8ms尾垫safe slot、原完整对象和映射基底key-onsets/hold/sound。附加内部Arrange只读反射检视用于独立raw note身份与slot证明，不替代公开主接口。

## 已执行（请勿重复覆盖证据）
- Build-Probe.ps1 -IncludeCoreTests：复用Pop100GapProbe脚本新副本，本目录artifacts/nuget/feed/tmp/cli-home隔离。
- Run-Probe.ps1 -Mode matrix -Output <NEW绝对matrix-*.json>：900+66对、300鼓组合，结果final已保存。
- Run-Probe.ps1 -Mode fixtures -Output <NEW绝对matrix-*.json>：38pair+4direct，包括14原生吉他和弦。
- Run-Probe.ps1 -Mode evidence -Output <NEW绝对matrix-*.json>：18 RecordingSink、8 staged software WAV后复制matrix-*；从未使用nativeSink/音频播放。
- Finalize-Reports.py：只读现有结果、源notes与保护哈希，生成报告/592分析/完整性。不得重复覆盖。

Run-CoreTests.ps1是保留的历史直接190套检查（132曲库），不是最新父191套验收。LegacyReleaseDiagnostic.cs.txt保留旧版12条差异的锁定DLL诊断代码；对应结果已保存，不再用新Core重解释旧结果。

最终结论和限制请看 D:\原神弹琴脚本\AutoMidiPlayer\.validation\smart-interludes-2026-10-06\matrix-final-report.md；没有部署/UD改动。主矩阵和额外66失败0、selected Hold/Sound变化0；592 residual是真实休止与greedy整音边界混合，不强填。884个added mapped sustain端点缩短仍单列。不做游戏音质/完整音乐证明。

父确认完成后本轮按用户要求已停止，不要自动扩展或重新播放/输入。代码沿用仓库GPL-3.0归属；LICENSE与QINBAN-NOTICES未改。
