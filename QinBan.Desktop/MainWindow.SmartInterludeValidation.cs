using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    // Validate before LibraryStore is constructed: a bad test invocation must not touch UserData.
    private static void EnsureSmartInterludeValidationIsolation(string? dataDirectory, bool uiTest, string? catalogDirectory)
    {
        string[] args = Environment.GetCommandLineArgs(); int at = Array.IndexOf(args, "--data-dir");
        if (!uiTest || !args.Contains("--ui-test") || args.Count(a => a == "--smart-interlude-validation") != 1
            || args.Count(a => a == "--data-dir") != 1 || at < 0 || at + 1 >= args.Length || dataDirectory == null)
            throw new InvalidOperationException("智能衔接自测必须使用 --ui-test --smart-interlude-validation 与显式独立 --data-dir。");
        string Canonical(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        bool Within(string path, string directory) => path.Equals(directory, StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        string data = Canonical(dataDirectory), catalog = Canonical(catalogDirectory ?? Path.Combine(AppContext.BaseDirectory, "Songs"));
        if (!data.Equals(Canonical(args[at + 1]), StringComparison.OrdinalIgnoreCase) || string.IsNullOrEmpty(Path.GetDirectoryName(data))
            || Within(data, catalog) || Within(catalog, data) || File.Exists(data)
            || data.Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar]).Any(p =>
                p.Equals("UserData", StringComparison.OrdinalIgnoreCase) || p.Equals("dist", StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("拒绝默认 / 既有 UserData、内置曲库、根目录或 dist 内的智能衔接自测数据目录。");
        // Only this already-isolated process may reopen the same test data, never an existing user's state.
        bool reopening = Application.Current.MainWindow is MainWindow owner && owner._uiTest && owner._store != null
            && data.Equals(Canonical(owner._store.DataDirectory), StringComparison.OrdinalIgnoreCase);
        if (!reopening && Directory.Exists(data) && Directory.EnumerateFileSystemEntries(data).Any())
            throw new InvalidOperationException("智能衔接自测的数据目录必须不存在或为空；不覆盖既有文件。请为本次运行指定新目录。");
    }

    private async Task RunSmartInterludeValidationAsync()
    {
        const int expectedBuiltinScores = 132;
        const string firstId = "builtin:pop909-035.json", secondId = "builtin:pop909-038.json";
        string? output = null; LibraryEntry? first = null, second = null;
        SongDocument? original = null; PlaybackPlan? manual = null; string? originalJson = null, initialOptions = null;
        var results = new List<object>(); var observations = new List<object>(); var notRun = new List<string>();
        var sourceHashes = new Dictionary<string, string>(); int cases = 0, failures = 0, reopenedNativeAttempts = 0;
        bool completed = false; int? observedBuiltinScores = null; MainWindow? reopened = null;
        void Check(bool ok, string why) { if (!ok) throw new InvalidOperationException(why); }
        async Task<bool> Test(string name, Func<Task> action)
        {
            ++cases; var watch = Stopwatch.StartNew();
            try { await action(); results.Add(new { name, status = "PASS", milliseconds = watch.Elapsed.TotalMilliseconds }); return true; }
            catch (Exception ex) { ++failures; results.Add(new { name, status = "FAIL", error = ex.ToString(), milliseconds = watch.Elapsed.TotalMilliseconds }); return false; }
        }
        string PlanJson(PlaybackPlan plan) => JsonSerializer.Serialize(plan, JsonDefaults.Options);
        string ManualOptionsJson(PlayOptions options)
        {
            var copy = options.Copy(); copy.SmartInterludes = null; return JsonSerializer.Serialize(copy, JsonDefaults.Options);
        }
        void CheckSafe(MainWindow window)
        {
            Check(window._uiTest && window.VolumeSlider.Value == 0 && window.QueueAutoCheck.IsChecked != true
                && window._hotkeys == null && !window._gameHotkeyEnabled && window._sink == null && window._engine == null
                && window._media == null && !window._previewActive && !window._rendering && window._launchCancel == null
                && !window._launchGate.Pending && window._nativeAttempts == 0 && window._validationUnhandled.Count == 0,
                "静音 / noOSinput 边界被破坏，或捕获到 Dispatcher 异常。");
        }
        void CheckPrepared(MainWindow window, string id, bool? savedValue, int[] tracks)
        {
            Check(!window._preparing && window._song != null && window._plan != null && window._preparedOptions != null
                && window._selected?.Id == id && window._lastPreparedScore != null, "选曲未成功准备或使用了旧计划：" + id);
            bool enabled = SmartInterludeArranger.IsEnabled(window._song!, window._preparedOptions!);
            var read = window.ReadOptions();
            Check(window.SmartInterludesCheck.IsChecked == enabled && read.SmartInterludes == enabled
                && window._preparedOptions!.SmartInterludes == savedValue && window._selected!.Options.SmartInterludes == savedValue,
                "开关、显式读取、准备快照或每歌状态不一致：" + id);
            Check(read.Tracks != null && read.Tracks.SequenceEqual(tracks)
                && window._preparedOptions!.Tracks != null && window._preparedOptions.Tracks.SequenceEqual(tracks)
                && window._selected!.Options.Tracks != null && window._selected.Options.Tracks.SequenceEqual(tracks), "选轨发生变化：" + id);
            Check(window._preparedOptions!.InstrumentId == window.SelectedInstrument.Id
                && window._plan!.Notes.All(n => window._keys.ContainsKey(n.Key))
                && window.ConversionText.Text == window._plan.Report.Summary, "乐器 / 映射报告未同步。");
            CheckSafe(window);
        }
        void CheckStored(string id, bool value, int[] tracks)
        {
            var store = new LibraryStore(_store.DataDirectory, _store.BuiltInDirectory);
            var saved = store.Find(id) ?? throw new InvalidOperationException("隔离数据库缺少曲谱：" + id);
            Check(saved.Options.SmartInterludes == value && saved.Options.Tracks != null && saved.Options.Tracks.SequenceEqual(tracks),
                "独立 LibraryStore 未读回显式开关和原选择：" + id);
        }
        async Task SelectSong(MainWindow window, string id)
        {
            var entry = window._store.Find(id) ?? throw new InvalidOperationException("缺少固定测试曲谱：" + id);
            window.SearchBox.Text = entry.Title; await window.WaitForLibraryAsync();
            var visible = window.SongList.Items.OfType<LibraryEntry>().Single(e => e.Id == id);
            window.SelectEntry(visible); await window.WaitForPreparationAsync();
            Check(window._selected?.Id == id && window.SongList.SelectedItem is LibraryEntry selected && selected.Id == id,
                "未按固定 ID 选中真实列表项：" + id);
        }
        void Observe(string stage)
        {
            observations.Add(new { stage, songId = _selected?.Id, enabled = SmartInterludesCheck.IsChecked,
                savedValue = _preparedOptions?.SmartInterludes, tracks = ReadOptions().Tracks, instrument = SelectedInstrument.Id,
                speed = _preparedOptions?.Speed, report = _plan?.Report, durationMs = _plan?.DurationMs });
        }
        async Task CaptureSwitch(string filename)
        {
            SetPage("library"); Width = 1460; Height = 940;
            ParametersToggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); UpdateLayout();
            SmartInterludesCheck.BringIntoView(); await Task.Delay(100); UpdateLayout();
            var bounds = SmartInterludesCheck.TransformToAncestor(ParameterOverlay).TransformBounds(
                new Rect(0, 0, SmartInterludesCheck.ActualWidth, SmartInterludesCheck.ActualHeight));
            Check(SmartInterludesCheck.IsVisible && bounds.Left >= 0 && bounds.Top >= 0
                && bounds.Right <= ParameterOverlay.ActualWidth + 1 && bounds.Bottom <= ParameterOverlay.ActualHeight + 1,
                "智能衔接开关不在截图视口内。");
            string path = Path.Combine(output!, filename); Capture(path);
            Check(new FileInfo(path).Length > 0, "开关截图未保存。");
        }
        try
        {
            EnsureSmartInterludeValidationIsolation(_store.DataDirectory, _uiTest, _store.BuiltInDirectory);
            output = Path.Combine(_store.DataDirectory, "smart-interlude-validation"); Directory.CreateDirectory(output);
            VolumeSlider.Value = 0; QueueAutoCheck.IsChecked = false; _timer.Stop();
            if (!await Test("隔离目录、静音、无播放器与 noOSinput 前置", async () =>
            {
                await WaitForLibraryAsync(); await WaitForPreparationAsync(); CheckSafe(this);
                Check(_store.Query(new(Filter: LibraryFilter.Personal, Limit: 1)).Total == 0 && !_store.MigratedLegacy
                    && _store.LoadWarnings.Count == 0, "隔离目录包含个人谱 / 迁移状态或加载警告。");
            })) { notRun.Add("安全前置失败；未执行选曲、保存状态和截图。"); return; }
            if (!await Test("当前 132 catalog 与固定 POP909 035 / 038", () =>
            {
                string catalog = Path.Combine(_store.BuiltInDirectory, LibraryCatalog.FileName);
                Check(File.Exists(catalog), "缺少当前 catalog.db，不接受回退索引作为验证。");
                var indexed = _store.Query(new(Filter: LibraryFilter.BuiltIn, Limit: 200)); observedBuiltinScores = indexed.Total;
                Check(indexed.Total == expectedBuiltinScores && indexed.Items.Count == expectedBuiltinScores && _store.Count == expectedBuiltinScores,
                    $"需要当前 132 catalog；实际内置 {indexed.Total} / 总谱目 {_store.Count}。");
                first = _store.Find(firstId) ?? throw new InvalidOperationException("缺少 " + firstId);
                second = _store.Find(secondId) ?? throw new InvalidOperationException("缺少 " + secondId);
                foreach (var entry in new[] { first, second })
                {
                    Check(entry.BuiltIn && entry.Provenance.Provider == "POP909" && entry.Options.SmartInterludes == null
                        && entry.Options.Tracks != null && entry.Options.Tracks.SequenceEqual(new[] { 1 }), "固定曲谱的来源 / 继承默认 / 选轨不符。");
                    string path = _store.ResolvePath(entry); sourceHashes.Add(path, LibraryCatalog.HashFile(path));
                }
                sourceHashes.Add(catalog, LibraryCatalog.HashFile(catalog)); return Task.CompletedTask;
            })) { notRun.Add("目录前置失败；后续智能衔接用例未执行。"); return; }
            await Test("_song 尚未加载时按 _selected.Provenance 继承默认，并尊重显式关闭", () =>
            {
                var savedSong = _song; var savedEntry = _selected; bool savedLoading = _loadingOptions;
                var savedOptions = ReadOptions(); _song = null; _loadingOptions = true;
                try
                {
                    _selected = first; LoadOptions(first!.Options); Check(SmartInterludesCheck.IsChecked == true, "POP909 未在准备前继承开启。");
                    var disabled = first.Options.Copy(); disabled.SmartInterludes = false; LoadOptions(disabled);
                    Check(SmartInterludesCheck.IsChecked == false && ReadOptions().SmartInterludes == false, "显式关闭被 POP909 默认覆盖。");
                    _selected = new LibraryEntry { Provenance = new() { Provider = "local" } }; LoadOptions(new());
                    Check(SmartInterludesCheck.IsChecked == false, "非 POP909 被自动开启。");
                    LoadOptions(new() { SmartInterludes = true }); Check(ReadOptions().SmartInterludes == true, "显式开启未被读取。");
                }
                finally { _selected = savedEntry; _song = savedSong; LoadOptions(savedOptions); _loadingOptions = savedLoading; }
                return Task.CompletedTask;
            });
            if (!await Test("035 继承开启：异步准备保留原选择 / 时间并展示补音报告", async () =>
            {
                await SelectSong(this, firstId); CheckPrepared(this, firstId, null, [1]);
                original = _song!; originalJson = SongParser.ToJson(original); var manualOptions = ReadOptions(); manualOptions.SmartInterludes = false;
                initialOptions = ManualOptionsJson(manualOptions); manual = GameMapping.Build(original, manualOptions);
                Check(_plan!.Report.InterludeNotes > 0 && _plan.Report.InterludeSegments > 0 && _plan.DurationMs == manual.DurationMs,
                    "035 未补入源声部，或智能衔接改变了时间轴。"); Observe("035 inherited");
            })) { notRun.Add("035 准备失败；依赖用例未执行。"); return; }
            await Test("关闭触发重新准备并持久化 false，完全还原手动计划与选轨", async () =>
            {
                int epoch = _prepareEpoch; var task = _prepareTask; SmartInterludesCheck.IsChecked = false;
                Check(_prepareEpoch > epoch && !ReferenceEquals(task, _prepareTask), "开关未触发现有准备管线。");
                await WaitForPreparationAsync(); CheckPrepared(this, firstId, false, [1]); CheckStored(firstId, false, [1]);
                Check(_plan!.Report.InterludeNotes == 0 && _plan.Report.InterludeSegments == 0 && PlanJson(_plan) == PlanJson(manual!)
                    && ManualOptionsJson(ReadOptions()) == initialOptions, "关闭未完全还原手动计划或修改了其他参数。");
                Observe("035 off"); await CaptureSwitch("smart-interlude-off-035.png");
            });
            await Test("重新开启保存显式 true，选择和参数不变，并捕获开关截图", async () =>
            {
                SmartInterludesCheck.IsChecked = true; await WaitForPreparationAsync(); CheckPrepared(this, firstId, true, [1]); CheckStored(firstId, true, [1]);
                Check(_plan!.Report.InterludeNotes > 0 && _plan.Report.InterludeSegments > 0
                    && _plan.DurationMs == manual!.DurationMs && ManualOptionsJson(ReadOptions()) == initialOptions, "开启改动了手动参数 / 时间。");
                Observe("035 on"); await CaptureSwitch("smart-interlude-on-035.png");
            });
            await Test("其他参数保存时保留智能开关与原选轨", async () =>
            {
                SpeedSlider.Value = 1.25; await WaitForPreparationAsync(); CheckPrepared(this, firstId, true, [1]);
                var saved = new LibraryStore(_store.DataDirectory, _store.BuiltInDirectory).Find(firstId)!;
                Check(saved.Options.Speed == 1.25 && saved.Options.SmartInterludes == true
                    && ManualOptionsJson(saved.Options) == ManualOptionsJson(ReadOptions()), "速度、智能开关或其他参数未一同保存。");
                CheckStored(firstId, true, [1]);
            });
            await Test("038 独立继承默认；关闭后只保留原手动选择", async () =>
            {
                await SelectSong(this, secondId); CheckPrepared(this, secondId, null, [1]);
                Check(_plan!.Report.InterludeNotes > 0 && _plan.Report.InterludeSegments > 0, "038 未补入源声部。");
                await CaptureSwitch("smart-interlude-on-038.png"); SmartInterludesCheck.IsChecked = false; await WaitForPreparationAsync();
                CheckPrepared(this, secondId, false, [1]); CheckStored(secondId, false, [1]);
                Check(_plan!.Report.InterludeNotes == 0 && PlanJson(_plan) == PlanJson(GameMapping.Build(_song!, ReadOptions())), "038 关闭未恢复手动计划。");
                Observe("038 off"); await CaptureSwitch("smart-interlude-off-038.png");
            });
            await Test("切曲每歌记忆：035 true / 1.25×，038 false / 1×", async () =>
            {
                await SelectSong(this, firstId); CheckPrepared(this, firstId, true, [1]); Check(SpeedSlider.Value == 1.25, "035 速度记忆丢失。");
                await SelectSong(this, secondId); CheckPrepared(this, secondId, false, [1]); Check(SpeedSlider.Value == 1, "038 被污染为 035 参数。");
                await SelectSong(this, firstId); CheckPrepared(this, firstId, true, [1]); Observe("per-song memory");
            });
            await Test("乐器切换保留每歌开关和选轨，重新适配合法键位", async () =>
            {
                InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().Single(i => i.Id == "voice");
                await WaitForPreparationAsync(); CheckPrepared(this, firstId, true, [1]);
                Check(SelectedInstrument.Id == "voice" && _keys.Count == 14 && _plan!.Report.InterludeNotes > 0, "声线适配未保留补音。");
                await SelectSong(this, secondId); CheckPrepared(this, secondId, false, [1]);
                Check(_plan!.Report.InterludeNotes == 0 && PlanJson(_plan) == PlanJson(GameMapping.Build(_song!, ReadOptions())), "换乐器偷开关闭状态。");
                InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().Single(i => i.Id == "windsong");
                await WaitForPreparationAsync(); await SelectSong(this, firstId); CheckPrepared(this, firstId, true, [1]); Observe("instrument return");
            });
            await Test("显式空选轨不偷启补音；开关切换与切曲仍保存空选择", async () =>
            {
                foreach (var check in TracksPanel.Children.OfType<CheckBox>()) check.IsChecked = false;
                await WaitForPreparationAsync(); CheckPrepared(this, firstId, true, []);
                foreach (bool enabled in new[] { false, true })
                {
                    SmartInterludesCheck.IsChecked = enabled; await WaitForPreparationAsync(); CheckPrepared(this, firstId, enabled, []);
                    Check(_plan!.Notes.Count == 0 && _plan.Report.InterludeNotes == 0 && _plan.Report.InterludeSegments == 0
                        && !PreviewButton.IsEnabled && !GameButton.IsEnabled, "空选轨生成了音符或启用播放。"); CheckStored(firstId, enabled, []);
                }
                await SelectSong(this, secondId); CheckPrepared(this, secondId, false, [1]);
                await SelectSong(this, firstId); CheckPrepared(this, firstId, true, []);
                Check(_plan!.Notes.Count == 0 && _plan.Report.InterludeNotes == 0, "切回后空选轨变成全部轨道。"); Observe("empty selection");
            });
            await Test("关掉并恢复原选轨后，计划与原手动基线逐字段一致", async () =>
            {
                SmartInterludesCheck.IsChecked = false; SpeedSlider.Value = 1;
                foreach (var check in TracksPanel.Children.OfType<CheckBox>()) check.IsChecked = (int)check.Tag == 1;
                await WaitForPreparationAsync(); CheckPrepared(this, firstId, false, [1]); CheckStored(firstId, false, [1]);
                Check(PlanJson(_plan!) == PlanJson(manual!) && ManualOptionsJson(ReadOptions()) == initialOptions
                    && SongParser.ToJson(_song!) == originalJson, "关闭未恢复原手动计划 / 参数，或修改了源谱。"); Observe("manual restored");
            });
            await Test("重建真实 MainWindow，从隔离存储恢复每歌 true / false 与选轨", async () =>
            {
                await SelectSong(this, secondId); SmartInterludesCheck.IsChecked = true; await WaitForPreparationAsync();
                CheckPrepared(this, secondId, true, [1]); CheckStored(secondId, true, [1]); await SelectSong(this, firstId); SavePreferences();
                // No Show / Loaded: do not dispatch a second validation or register hotkeys. IDs are test-only selections.
                reopened = new MainWindow(_store.DataDirectory, uiTest: true, validationCatalog: _store.BuiltInDirectory);
                reopened._timer.Stop(); reopened.VolumeSlider.Value = 0; reopened.QueueAutoCheck.IsChecked = false;
                await reopened.WaitForLibraryAsync(); await reopened.WaitForPreparationAsync();
                await SelectSong(reopened, firstId); CheckPrepared(reopened, firstId, false, [1]);
                Check(PlanJson(reopened._plan!) == PlanJson(manual!), "重开后关闭状态没有恢复手动基线。");
                await SelectSong(reopened, secondId); CheckPrepared(reopened, secondId, true, [1]);
                Check(reopened._plan!.Report.InterludeNotes > 0, "重开后显式开启未恢复补音。");
                CheckSafe(reopened); reopenedNativeAttempts += reopened._nativeAttempts; reopened.Close(); reopened = null;
            });
            await Test("结束安全状态、源 JSON 与当前 catalog 未变", () =>
            {
                CheckSafe(this); Check(_previewCleanupWarnings.Count == 0 && reopenedNativeAttempts == 0, "清理警告或重开窗口产生原生输入。");
                foreach (var pair in sourceHashes) Check(LibraryCatalog.HashFile(pair.Key) == pair.Value, "源谱 / catalog 被改动：" + pair.Key);
                return Task.CompletedTask;
            });
            completed = true;
        }
        catch (Exception ex) { ++failures; results.Add(new { name = "智能衔接自测驱动", status = "FAIL", error = ex.ToString() }); }
        finally
        {
            try
            {
                if (reopened != null) { reopenedNativeAttempts += reopened._nativeAttempts; reopened.EmergencyStop("智能衔接自测结束"); reopened.Close(); }
                EmergencyStop("智能衔接自测结束");
            }
            catch (Exception ex) { ++failures; results.Add(new { name = "自测结束安全停止", status = "FAIL", error = ex.ToString() }); }
            try
            {
                if (output == null) throw new InvalidOperationException("没有安全输出目录；拒绝写入智能衔接自测报告。");
                File.WriteAllText(Path.Combine(output, "smart-interlude-ui-report.json"), JsonSerializer.Serialize(new
                {
                    cases, failures, completed, expectedBuiltinScores, observedBuiltinScores, songIds = new[] { firstId, secondId },
                    nativeSendAttempts = _nativeAttempts + reopenedNativeAttempts, dataDirectory = _store.DataDirectory, builtInDirectory = _store.BuiltInDirectory,
                    mode = "仅隔离 WPF UI / 参数 / 准备验证；不自动播放、不发送 OS 按键、不证明游戏内演奏效果。",
                    physicalAudioOutput = "NOT TESTED; volume 0; MediaPlayer never started", gamePlayback = "NOT TESTED; noOSinput via --ui-test",
                    reopenMode = "new WPF MainWindow in the same isolated process, no Show/Loaded; explicit song IDs only in validation",
                    results, observations, sourceHashes, screenshots = _captureViewports, notRun,
                    dispatcherExceptions = _validationUnhandled, previewCleanupWarnings = _previewCleanupWarnings
                }, JsonDefaults.Options));
            }
            catch (Exception ex) { ++failures; Console.Error.WriteLine("智能衔接 UI 报告写入失败；专项不能通过：" + ex); }
            finally { Application.Current.Shutdown(completed && failures == 0 ? 0 : 1); }
        }
    }
}
