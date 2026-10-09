# 琴伴源码构建与验证

## 环境与入口

- Windows x64；桌面项目使用 WPF。
- .NET 10 SDK；Python 3 用于生成可复现教学样本；Git 用于克隆。
- 构建 `QinBan.slnx`，运行 `QinBan.Desktop`。`AutoMidiPlayer.*` 与 `build.ps1` 是上游参考，不是琴伴入口。

```powershell
git clone https://github.com/Anyes666/Qinban.git
cd Qinban

# 全新克隆没有 Songs；仅在空教学库中使用，勿覆盖已有曲库
python .\tools\generate_builtin.py
.\build-qinban.ps1 -Mode build
.\build-qinban.ps1 -Mode test
dotnet run --project .\QinBan.Desktop -c Release
```

生成器离线生成 30 份传统 / 古典教学片段和原创练习，不下载流行歌曲。它写入 `Songs/01.json` 等固定文件名及教学清单，**不能直接在已有完整曲库上重复运行**。这些教学片段也不是完整歌曲库；默认中文主力筛选为空时切换“全部曲库”。

`QinBan.Tests` 是可执行测试程序，使用 `dotnet run`，不是 `dotnet test`。测试结果写入独立 `.validation/core-*`。所有输入验证用记录器，禁止自动化向游戏发送真实按键。

## 发布自包含包

```powershell
.\build-qinban.ps1 -Mode publish
```

脚本输出到源码根目录的**父目录**下 `dist/QinBan-0.4.2-win-x64`，版本取自 Desktop 工程。已有同名目录时拒绝覆盖，防止改写运行包和个人数据；保留旧包后再决定升级方式。

脚本复制当前使用说明、许可证、项目内素材及相关文档。全新克隆没有本地 `verification/0.4.2` 证据，打包会明确提示“未附本地验证证据”，不会把历史本机测试当成新包验证。现有图标和背景素材的公开再分发权利未全部核验，**生成本地包不意味着可以公开发布该包**。商业曲谱和个人数据不应加入包。

## 安全的便携包自测

为每次验证指定一个尚不存在的输出目录：

```powershell
# 全新教学包含 30 谱；验证自己有其他曲库的包时填入实际预期数量
.\tools\validate-portable.ps1 -Mode cold-start `
  -Executable ..\dist\QinBan-0.4.2-win-x64\QinBan.exe `
  -OutputRoot .\.validation\cold-teaching-01 -ExpectedBuiltins 30
```

当前完整 `-Mode ui` 测试还包含中文候选筛选断言，需要本地受控中文曲库，**不适用于仅有 30 教学谱的公开克隆**。CI 因此只运行构建和核心记录器测试，不伪报完整曲库 UI 测试通过。

2026-10-10 的首页截图来自既有本地运行包，不是 CI 生成的新包；本次本机无 .NET SDK，未重跑源码构建 / 核心测试，已运行的是该自包含包的冷启动与界面自测。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `QinBan.Core` | 曲谱解析、目录检索、乐器映射、播放逻辑 |
| `QinBan.Desktop` | 琴伴 WPF 窗口、试听、安全输入与界面自测 |
| `QinBan.Tests` | 核心记录器测试 |
| `QinBan.LibraryTools` | 受控曲库工具 |
| `tools` | 构建配套、教学样本和验证脚本 |
| `docs/images` | 本次真实运行截图，不含原始私人桌面 |
| `docs/history` | 上游原说明与既有研发记录，仅作历史参考 |

请先阅读仓库 `AGENTS.md` 和[贡献指南](../CONTRIBUTING.md)。公开范围见[发布范围说明](../REPOSITORY-PUBLISHING-SCOPE.md)。
