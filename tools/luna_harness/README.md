# Luna Score Harness G0

这是琴伴批量曲谱 Harness 的首个可执行 G0 实现，采用“单主控 + 确定性离线工作进程”回退模式。它不是操作系统沙箱，也不执行网络下载、音频转写、MIDI 制谱、原神输入或生产曲库写入。

## 已实现

- 新运行目录：`.validation/luna-score-runs/<run_id>`，冲突时拒绝复用。
- 当前策略、任务/结果 Schema、输入文件 SHA256 与 150 个受保护源码/EXE/谱文件的运行前重核。
- 规范 JSON 读取：拒绝重复键、NaN/Infinity、过深 JSON。
- 规范路径检查：相对路径、canonical containment、Windows symlink/junction/reparse-point fail-closed。
- 任务提交、单写入者边界、输入快照绑定、输出目录绑定、append-only checkpoint 链、lease 与孤儿 lease 恢复。
- 精确的 Python `luna_harness.worker` 命令 allowlist、子进程退出码、结果与报告 SHA256 绑定。
- 资源准入（内存/磁盘）、最大外部调用为 0、原生按键尝试必须为 0。
- 独立 checker：不依赖 controller 状态，重新读取策略/Schema/任务/结果/报告/基线。
- G1 只读来源容量审计：列出 10 个可追溯候选；候选目录不计曲谱，实际现代目标谱文件取得数保持 0。

## 最小命令

在 `AutoMidiPlayer/tools` 下设置 `PYTHONPATH` 后运行：

```powershell
$env:PYTHONPATH='D:\原神弹琴脚本\AutoMidiPlayer\tools'
python -B -m luna_harness create-run --run-id <unique-run-id>
python -B -m luna_harness submit --run-root <run> --task <task.json>
python -B -m luna_harness run-queue --run-root <run> --recover
python -B -m luna_harness check-run --run-root <run> --output <run>\reports\independent-check.json
python -B -m luna_harness.source_audit --workspace 'D:\原神弹琴脚本' --output <run>\reports\source-capacity-audit.json
```

`self_test` 只使用临时隔离目录和控制夹具：

```powershell
python -B -m luna_harness.self_test --output <run>\reports\g0-self-test.json
```

## 明确边界

- worker `SUCCEEDED` 只代表受控小任务完成，不是曲谱准确、人工听辨、游戏实测、许可、正式 A/B 入库或部署批准。
- `candidate_score` 在 G0 worker 中会进入 `QUARANTINED/SOURCE_NOT_ACQUIRED`，不会根据歌名猜音符。
- 生产云代理、网络获取、GPU 转写、自动部署、Songs/UserData 写入仍关闭；当前策略文件保持“规范交付、未宣称生产代理”的历史状态。
- Windows 当前账户无法创建 symlink 时，self-test 会将该运行时案例记为 SKIP；代码路径仍对 reparse-point fail-closed，需在具备可创建测试链接权限的隔离环境补测。
