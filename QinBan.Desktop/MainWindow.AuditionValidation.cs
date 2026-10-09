using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    // Test-only. An external expectation must never be inferred from the observed catalogue.
    private static bool TryGetCaptureExpectedBuiltins(out int expected, out string? error)
    {
        expected = 30; error = null;
        string[] args = Environment.GetCommandLineArgs();
        int at = Array.IndexOf(args, "--expected-builtins");
        if (at < 0) return true;
        if (args.Count(a => a == "--expected-builtins") != 1 || at + 1 >= args.Length
            || !int.TryParse(args[at + 1], NumberStyles.None, CultureInfo.InvariantCulture, out int value)
            || value is < 1 or > 100000)
        {
            error = "--expected-builtins 必须且只能指定一次整数 N，范围为 1..100000。";
            return false;
        }
        expected = value; return true;
    }

    private async Task RunAuditionValidationAsync(Exception? startupError = null)
    {
        const int expectedBuiltinScores = 32;
        string? output = null;
        var results = new List<object>(); var exceptions = new List<object>();
        var instrumentMatrix = new List<object>(); var songMetadata = new List<object>();
        var notRun = new List<string>(); var sourceHashes = new Dictionary<string, string>();
        int cases = 0, failures = 0; bool completed = false;
        LibraryPage? indexed = null;
        var songs = new[] { (Title: "日不落", Artist: "蔡依林", Slug: "ribuluo"), (Title: "美人鱼", Artist: "林俊杰", Slug: "meirenyu") };
        void Check(bool ok, string why) { if (!ok) throw new InvalidOperationException(why); }
        async Task<bool> Test(string name, Func<Task> action)
        {
            ++cases; var watch = Stopwatch.StartNew();
            try
            {
                await action(); results.Add(new { name, status = "PASS", milliseconds = watch.Elapsed.TotalMilliseconds }); return true;
            }
            catch (Exception ex)
            {
                ++failures;
                results.Add(new { name, status = "FAIL", error = ex.ToString(), milliseconds = watch.Elapsed.TotalMilliseconds });
                exceptions.Add(new { name, type = ex.GetType().FullName, error = ex.ToString() }); return false;
            }
        }
        void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        string Canonical(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        bool Within(string path, string directory) => Canonical(path).Equals(Canonical(directory), StringComparison.OrdinalIgnoreCase)
            || Canonical(path).StartsWith(Canonical(directory) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        string ProvenanceJson(ScoreProvenance provenance) => JsonSerializer.Serialize(provenance, JsonDefaults.Options);
        void CheckMetadata(LibraryEntry entry, SongDocument original, string artist)
        {
            var p = original.Provenance;
            Check(!p.Synthetic && !p.IsFormalSong && !entry.Provenance.Synthetic && !entry.Provenance.IsFormalSong, "试听谱被误标为合成夹具或正式歌曲。");
            Check(p.MusicReview != "human-reviewed" && p.GameReview != "verified-arrangement"
                && (entry.QualityText.Contains("待核验") || entry.QualityText.Contains("未人工精校")), "待审 / 未游戏验收边界丢失。");
            Check(p.Artists.Contains(artist) && p.LanguageTags.Count > 0 && p.LanguageTags.Any(t => t != "und")
                && !string.IsNullOrWhiteSpace(p.VersionLabel), "歌手列表、明确语种或版本缺失。");
            Check(ProvenanceJson(entry.Provenance) == ProvenanceJson(p), "索引与实际谱子的 provenance 不一致。");
            Check(!string.IsNullOrWhiteSpace(original.Source) && !string.IsNullOrWhiteSpace(p.SourceUrl)
                && !string.IsNullOrWhiteSpace(p.Provider) && original.Warnings.Count > 0, "来源或源谱警告缺失。");
            Check(NowAuthor.Text.Contains(SongMetadata.ArtistText(p)) && NowAuthor.Text.Contains(SongMetadata.LanguageText(p))
                && NowAuthor.Text.Contains(p.VersionLabel), "当前谱的 WPF 歌手 / 语种 / 版本丢失。");
            Check(NowAuthor.ToolTip is string tooltip && tooltip.Contains("作者 / 编谱者：" + MetadataValue(original.Author))
                && tooltip.Contains("专辑：" + MetadataValue(p.Album)) && tooltip.Contains(p.VersionLabel), "当前谱的元数据提示不完整。");
            foreach (string text in new[] { original.Source, original.Description, p.SourceUrl, p.Provider, entry.QualityText,
                "音乐审校：" + MetadataValue(p.MusicReview), "游戏实测：" + MetadataValue(p.GameReview), p.VersionLabel })
                Check(SourceText.Text.Contains(text), "来源面板未保留：" + text);
            Check(SourceText.ToolTip is string sourceTooltip && sourceTooltip == SourceText.Text, "来源面板提示与正文不一致。");
        }
        void CheckReady(LibraryEntry entry, SongDocument original, InstrumentProfile instrument, string artist)
        {
            Check(_selected?.Id == entry.Id && _song != null && !_preparing && _lastPreparedScore != null
                && _plan != null && _preparedOptions?.InstrumentId == instrument.Id, "实际选曲 / 准备 / 乐器计划未就绪。");
            Check(SongParser.ToJson(_song!) == SongParser.ToJson(original), "切换乐器改变了真实源谱、元数据或警告。");
            CheckMetadata(entry, original, artist);
            Check(SelectedInstrument.Id == instrument.Id && Roll.Instrument.Id == instrument.Id && ReferenceEquals(Roll.Plan, _plan), "WPF 乐器 / 时间轴与计划不一致。");
            var buttons = KeysPanel.Children.OfType<Button>().ToArray();
            Check(buttons.Length == KeysPanel.Children.Count && buttons.Length == instrument.Keys.Count && _keys.Count == instrument.Keys.Count
                && KeysPanel.Rows == Math.Max(1, (instrument.Keys.Count + 6) / 7), "实际 WPF 键数 / 排数与乐器不符。");
            foreach (var key in instrument.Keys)
            {
                Check(_keys.TryGetValue(key.Key, out var button) && buttons.Contains(button)
                    && button.Tag is char tag && tag == key.Key, "实际 WPF 键位缺失：" + key.Key);
                var labels = (button!.Content as StackPanel)?.Children.OfType<TextBlock>().Select(t => t.Text).ToArray();
                Check(labels != null && labels.SequenceEqual(new[] { key.Key.ToString(), key.Label }), "实际 WPF 键标签错误：" + key.Key);
            }
            var plan = _plan!;
            Check(plan.Report.Original == original.Notes.Count && plan.Report.Output == plan.Notes.Count
                && ConversionText.Text == plan.Report.Summary && !ConversionText.Text.Contains("无损")
                && !ConversionText.Text.Contains("完全还原"), "适配报告被隐藏或误称无损还原。");
            Check(plan.Warnings.Take(original.Warnings.Count).SequenceEqual(original.Warnings)
                && plan.Warnings.Contains(instrument.Name + "：" + instrument.Note)
                && WarningsText.Text == string.Join("\n", plan.Warnings), "源谱 / 乐器警告未完整保留到计划和 WPF。");
            Check(double.IsFinite(plan.DurationMs) && plan.DurationMs >= 0, "计划总时长无效。");
            var allowed = instrument.Keys.ToDictionary(k => k.Key);
            var tracks = original.Tracks.Select(t => t.Id).ToHashSet();
            foreach (var note in plan.Notes)
            {
                Check(allowed.TryGetValue(note.Key, out var key) && _keys.ContainsKey(note.Key), "计划含非法按键：" + note.Key);
                Check(note.Pitch == key!.Pitches[0] && (key.IsChord
                    ? note.ChordPitches != null && note.ChordPitches.SequenceEqual(key.Pitches) : note.ChordPitches == null), "音高 / 和弦与所选乐器键位不符。");
                Check(double.IsFinite(note.StartMs) && note.StartMs >= 0 && double.IsFinite(note.HoldMs) && note.HoldMs > 0
                    && double.IsFinite(note.SoundMs) && note.SoundMs > 0 && note.StartMs + note.HoldMs <= plan.DurationMs + .01
                    && note.Velocity is >= 1 and <= 127 && tracks.Contains(note.Track) && note.Sustain == instrument.SupportsSustain,
                    "计划元素的时值、力度、轨道或延音不合法。");
            }
            Check(plan.Notes.SequenceEqual(plan.Notes.OrderBy(n => n.StartMs).ThenBy(n => n.Pitch)), "计划事件未按时序排列。");
            if (instrument.CanAutoPlay) Check(plan.Notes.Count > 0 && PreviewButton.IsEnabled, "可自动演奏乐器没有有效试听计划。");
            else Check(plan.Notes.Count == 0 && plan.DurationMs == 0 && buttons.Length == 0
                && !PreviewButton.IsEnabled && !GameButton.IsEnabled && WarningsText.Text.Contains("待核验"), "待核验鼓类仍生成音符或启用播放。");
        }
        try
        {
            string[] args = Environment.GetCommandLineArgs(); int at = Array.IndexOf(args, "--data-dir");
            Check(_uiTest && args.Contains("--audition-validation") && args.Count(a => a == "--data-dir") == 1 && at >= 0 && at + 1 < args.Length,
                "专项仅允许 --ui-test --audition-validation 与显式独立 --data-dir。");
            string data = Canonical(_store.DataDirectory), parent = Canonical(Path.GetDirectoryName(data)!);
            Check(data.Equals(Canonical(args[at + 1]), StringComparison.OrdinalIgnoreCase)
                && !data.Equals(Canonical(Path.Combine(AppContext.BaseDirectory, "UserData")), StringComparison.OrdinalIgnoreCase)
                && !Within(data, _store.BuiltInDirectory) && !Within(parent, _store.BuiltInDirectory)
                && !data.Split([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar]).Any(p => p.Equals("dist", StringComparison.OrdinalIgnoreCase)),
                "拒绝默认 UserData、Songs / 内置目录或 dist 内的数据 / 报告输出。");
            output = parent; Directory.CreateDirectory(output);
            if (startupError != null) throw new InvalidOperationException("等待曲库 / 准备的异步启动失败。", startupError);
            if (!await Test("独立数据目录、静音与 test-only 输入锁", () =>
            {
                VolumeSlider.Value = 0; QueueAutoCheck.IsChecked = false;
                Check(_store.Query(new(Filter: LibraryFilter.Personal, Limit: 1)).Total == 0 && !_store.MigratedLegacy
                    && _store.LoadWarnings.Count == 0, "数据目录不是无个人谱的隔离目录，或曲库加载有警告。");
                Check(VolumeSlider.Value == 0 && _media == null && _sink == null && _engine == null
                    && _hotkeys == null && !_gameHotkeyEnabled && _launchCancel == null && _nativeAttempts == 0, "静音 / 输入安全前置失败。");
                return Task.CompletedTask;
            })) { notRun.Add("安全前置失败，未进行选曲、乐器、试听和截图。"); return; }
            if (!await Test("新包索引为 30 教学 + 2 真实作品待审试听 = 32", async () =>
            {
                string catalog = Path.Combine(_store.BuiltInDirectory, LibraryCatalog.FileName);
                Check(File.Exists(catalog), "新包缺少内置 catalog.db，不能以回退建索引替代包验证。");
                indexed = _store.Query(new(Filter: LibraryFilter.BuiltIn, Limit: 50));
                Check(indexed.Total == expectedBuiltinScores && indexed.Items.Count == expectedBuiltinScores && _store.Count == expectedBuiltinScores,
                    $"需要主线 32 曲包；实际内置索引 {indexed.Total}，实际总谱目 {_store.Count}。");
                Check(indexed.Items.Count(e => e.Provenance.Completeness == "exercise") == 30
                    && indexed.Items.Count(e => e.Provenance.Completeness != "exercise") == 2
                    && indexed.Items.All(e => e.BuiltIn && !e.Provenance.Synthetic && !e.Provenance.IsFormalSong), "30 教学 / 2 试听分类或非 formal 边界错误。");
                Check(_store.Statistics().FormalSongs == 0, "待审试听被计入正式歌曲。");
                var choices = InstrumentCombo.Items.OfType<InstrumentChoice>().ToArray();
                Check(choices.Length == 12 && choices.Select(i => i.Id).Distinct().Count() == 12
                    && choices.Count(i => i.Profile.CanAutoPlay) == 9 && choices.Count(i => !i.Profile.CanAutoPlay) == 3, "需要 9 个 CanAutoPlay 乐器及 3 个禁用鼓。");
                SetPage("library"); FilterCombo.SelectedIndex = (int)LibraryFilter.BuiltIn; QualityCombo.SelectedIndex = 0;
                PlaylistCombo.SelectedIndex = 0; SearchBox.Clear(); _libraryOffset = 0; RefreshLibrary(); await WaitForLibraryAsync();
                Check(_libraryPage?.Total == expectedBuiltinScores && SongList.Items.Count == expectedBuiltinScores, "真实 WPF 列表不是 32 项。");
                sourceHashes.Add(catalog, LibraryCatalog.HashFile(catalog));
                foreach (var entry in indexed.Items) { string path = _store.ResolvePath(entry); sourceHashes.Add(path, LibraryCatalog.HashFile(path)); }
            })) { notRun.Add("32 曲包 / 索引前置失败，未进行两曲、乐器、试听和截图。"); return; }
            foreach (var spec in songs)
            {
                LibraryEntry? entry = null; SongDocument? original = null;
                if (!await Test($"{spec.Artist}《{spec.Title}》组合搜索唯一匹配", async () =>
                {
                    var candidate = indexed!.Items.Single(e => e.Title.Contains(spec.Title) && e.Provenance.Artists.Contains(spec.Artist));
                    Check(candidate.Provenance.VersionLabel.Length > 0 && candidate.Provenance.LanguageTags.Count > 0, "搜索的版本 / 语种前置缺失。");
                    string language = SongMetadata.LanguageText(new() { LanguageTags = [candidate.Provenance.LanguageTags[0]] });
                    SearchBox.Text = $"{spec.Title} {spec.Artist} {language} {candidate.Provenance.VersionLabel}";
                    await WaitForLibraryAsync();
                    Check(_libraryPage?.Total == 1 && SongList.Items.Count == 1, "组合搜索未唯一找到：" + SearchBox.Text);
                    entry = SongList.Items.OfType<LibraryEntry>().Single();
                    Check(entry.Id == candidate.Id && entry.BuiltIn, "组合搜索命中了错误作品 / 版本。");
                    original = SongParser.Read(_store.ResolvePath(entry));
                })) { notRun.Add($"{spec.Title}搜索前置失败，未运行该曲的选曲、12 乐器、试听和截图。"); continue; }
                bool ready = await Test($"{spec.Artist}《{spec.Title}》真实选曲、准备、元数据与合法计划", async () =>
                {
                    InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "windsong");
                    SongList.SelectedItems.Clear(); SongList.SelectedItem = entry;
                    await WaitForPreparationAsync();
                    CheckReady(entry!, original!, SelectedInstrument, spec.Artist);
                    SongList.ScrollIntoView(entry); UpdateLayout(); await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Loaded); UpdateLayout();
                    var container = SongList.ItemContainerGenerator.ContainerFromItem(entry) as ListBoxItem;
                    Check(container != null, "实际选中曲目的 WPF 列表项未实现。");
                    var metadata = MetadataVisuals(container!).OfType<TextBlock>().Single(t => t.Text == entry!.MetadataText);
                    Check(metadata.ToolTip is string tooltip && tooltip.Contains(entry!.MetadataText)
                        && tooltip.Contains("作者 / 编谱者：" + entry.Author), "实际列表的歌手 / 语种 / 版本提示不完整。");
                });
                songMetadata.Add(new { title = spec.Title, artist = spec.Artist, entryId = entry!.Id, catalogTitle = entry.Title, entry.RelativePath,
                    resourceSha256 = LibraryCatalog.HashFile(_store.ResolvePath(entry)), indexProvenance = entry.Provenance,
                    scoreProvenance = original!.Provenance, original.Source, original.Description, sourceWarnings = original.Warnings,
                    isFormalSong = original.Provenance.IsFormalSong, quality = entry.QualityText, search = SearchBox.Text,
                    prepared = ready, displayedMetadata = NowAuthor.Text, displayedSource = SourceText.Text, displayedWarnings = WarningsText.Text });
                if (!ready) { notRun.Add($"{spec.Title}真实选曲 / 准备失败，未运行该曲的12乐器、试听和截图。"); continue; }
                foreach (var choice in InstrumentCombo.Items.OfType<InstrumentChoice>())
                {
                    bool passed = false;
                    await Test($"{spec.Title} / {choice.Name}：实际 WPF 键位、计划与警告", async () =>
                    {
                        try
                        {
                            InstrumentCombo.SelectedItem = choice; await WaitForPreparationAsync(); UpdateLayout();
                            CheckReady(entry, original, choice.Profile, spec.Artist); passed = true;
                        }
                        finally
                        {
                            instrumentMatrix.Add(new { song = spec.Title, artist = spec.Artist, instrumentId = choice.Id, instrumentName = choice.Name,
                                choice.Profile.CanAutoPlay, status = passed ? "PASS" : "FAIL", expectedKeys = choice.Profile.Keys.Count,
                                wpfButtonCount = KeysPanel.Children.OfType<Button>().Count(), keyMapCount = _keys.Count, preparedInstrument = _preparedOptions?.InstrumentId,
                                plannedNotes = _plan?.Notes.Count, durationMs = _plan?.DurationMs, conversion = _plan?.Report,
                                warnings = _plan?.Warnings, displayedWarnings = WarningsText.Text, previewEnabled = PreviewButton.IsEnabled,
                                gameEnabled = GameButton.IsEnabled, isFormalSong = _song?.Provenance.IsFormalSong,
                                losslessClaim = false, nativeSendAttempts = _nativeAttempts });
                        }
                    });
                }
                string? previewPath = null; PlaybackPlan? previewReadyPlan = null;
                await Test($"{spec.Title}真实试听按钮启动 WPF MediaPlayer（强制静音）", async () =>
                {
                    try
                    {
                        InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "windsong");
                        await WaitForPreparationAsync(); CheckReady(entry, original, SelectedInstrument, spec.Artist);
                        VolumeSlider.Value = 0; SeekTo(0); previewReadyPlan = _plan;
                        Check(_uiTest && VolumeSlider.Value == 0 && PreviewButton.IsEnabled, "禁止非 ui-test 或非静音试听。");
                        Click(PreviewButton);
                        var watch = Stopwatch.StartNew();
                        while (!_previewActive && watch.Elapsed < TimeSpan.FromSeconds(90))
                        {
                            Check(_validationUnhandled.Count == 0, "等待试听时出现 Dispatcher 异常。");
                            if (!_rendering && _media == null) throw new InvalidOperationException("试听按钮未成功生成 / 打开音频：" + StatusText.Text);
                            await Task.Delay(25);
                        }
                        Check(_previewActive && !_previewPaused && _media != null && _media.Volume == 0
                            && ReferenceEquals(_previewPlan, previewReadyPlan), "MediaPlayer 未开始静音播放：" + StatusText.Text);
                        previewPath = _previewFile;
                        Check(previewPath != null && File.Exists(previewPath), "实际 WPF 试听未使用本次生成的 WAV。");
                        double start = _media!.Position.TotalMilliseconds;
                        var playbackStarted = Stopwatch.StartNew();
                        while (_media != null && _media.Position.TotalMilliseconds <= start && playbackStarted.Elapsed < TimeSpan.FromSeconds(2)) await Task.Delay(25);
                        Check(_media != null && _media.Volume == 0 && _media.Position.TotalMilliseconds > start, "静音播放位置未开始推进。");
                    }
                    finally { Click(StopButton); UpdatePlaybackView(); }
                });
                await Test($"{spec.Title}真实停止按钮恢复安全状态与就绪计划", () =>
                {
                    Check(!_previewActive && !_previewPaused && !_rendering && _media == null && _previewCancel == null && _previewFile == null,
                        "停止后试听 / 音频生成状态未恢复。");
                    Check(previewPath == null || !File.Exists(previewPath), "停止后本次试听 WAV 未清理。");
                    Check(previewReadyPlan != null && ReferenceEquals(_plan, previewReadyPlan) && PreviewButton.IsEnabled && !_preparing
                        && PauseButton.Content?.ToString() == "暂停" && PreviewButton.Content?.ToString() == "本地试听"
                        && ModeLabel.Text == "安全模式 · 仅本地试听" && _keys.Values.All(b => ReferenceEquals(b.Background, _normalKey)), "停止后计划、按钮或高亮未恢复。");
                    Check(_sink == null && _launchCancel == null && !_launchGate.Pending && _nativeAttempts == 0, "试听 / 停止触发了真实输入。");
                    return Task.CompletedTask;
                });
                foreach (int width in new[] { 1460, 1080 })
                {
                    await Test($"{spec.Title}真实 WPF {width} 宽截图", async () =>
                    {
                        CheckReady(entry, original, SelectedInstrument, spec.Artist);
                        WindowState = WindowState.Normal; Width = width; Height = width == 1460 ? 940 : 720;
                        AdaptationExpander.IsExpanded = true; WorkbenchScroll.ScrollToTop(); UpdateLayout();
                        await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Render); await Task.Delay(100); UpdateLayout();
                        Check(Math.Abs(ActualWidth - width) < 1 && NowTitle.Text == original.Title && NowAuthor.IsVisible && NowAuthor.ActualWidth > 0,
                            "截图视口或真实主曲元数据不正确。");
                        CheckFooterBounds(); string path = Path.Combine(output!, $"audition-{spec.Slug}-{width}.png");
                        int before = _captureViewports.Count; Capture(path);
                        Check(new FileInfo(path).Length > 0 && _captureViewports.Count == before + 1, "现有 Capture 未生成截图及视口记录。");
                    });
                }
            }
            completed = true;
        }
        catch (Exception ex)
        {
            ++cases; ++failures; results.Add(new { name = "audition validation driver", status = "FAIL", error = ex.ToString() });
            exceptions.Add(new { name = "audition validation driver", type = ex.GetType().FullName, error = ex.ToString() });
            notRun.Add("专项驱动异常，中断的后续检查未运行。");
        }
        finally
        {
            await Test("专项结束：无原生输入 / Dispatcher 异常 / 清理警告，内置源与索引不变", () =>
            {
                EmergencyStop("试听专项工程 / 界面测试结束"); UpdatePlaybackView();
                Check(_nativeAttempts == 0 && _sink == null && _engine?.IsRunning != true && !_gameHotkeyEnabled && _hotkeys == null
                    && _launchCancel == null && !_launchGate.Pending && !_previewActive && !_rendering && _media == null, "专项结束未恢复安全状态或产生真实输入。");
                Check(_validationUnhandled.Count == 0, string.Join("\n", _validationUnhandled));
                Check(_previewCleanupWarnings.Count == 0, string.Join("\n", _previewCleanupWarnings));
                foreach (var pair in sourceHashes) Check(File.Exists(pair.Key) && LibraryCatalog.HashFile(pair.Key) == pair.Value, "内置谱 / 索引被修改：" + pair.Key);
                return Task.CompletedTask;
            });
            try
            {
                if (output == null) throw new InvalidOperationException("没有安全的独立数据 / 输出目录；拒绝写入 audition-ui-report.json。");
                File.WriteAllText(Path.Combine(output, "audition-ui-report.json"), JsonSerializer.Serialize(new
                {
                    cases, failures, completed, expectedBuiltinScores, observedBuiltinScores = indexed?.Total,
                    nativeSendAttempts = _nativeAttempts, dataDirectory = _store.DataDirectory, builtInDirectory = _store.BuiltInDirectory,
                    mode = "仅工程 / WPF 界面专项验证；真实作品待审试听谱，非人工听辨、非正式歌曲认证、非游戏验收。",
                    physicalAudioOutput = "NOT TESTED; all preview playback forced to volume 0",
                    humanListening = "NOT TESTED", gamePlayback = "NOT TESTED; native input prohibited by --ui-test",
                    results, instrumentMatrix, songMetadata, screenshots = _captureViewports, exceptions, notRun,
                    dispatcherExceptions = _validationUnhandled, previewCleanupWarnings = _previewCleanupWarnings
                }, JsonDefaults.Options));
            }
            catch (Exception ex)
            {
                ++failures; Console.Error.WriteLine("audition-ui-report.json 写入失败；专项不能通过：" + ex);
            }
            finally { Application.Current.Shutdown(failures == 0 ? 0 : 1); }
        }
    }
}
