using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow : Window
{
    private readonly LibraryStore _store;
    private readonly bool _uiTest;
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMilliseconds(60) };
    private readonly Dictionary<char, Button> _keys = [];
    private readonly Brush _normalKey = new SolidColorBrush(Color.FromRgb(32, 47, 60));
    private Brush _activeKey = new SolidColorBrush(Color.FromRgb(67, 107, 111));
    private LibraryEntry? _selected;
    private SongDocument? _song;
    private PlaybackPlan? _plan;
    private bool _ready, _loadingOptions, _closing, _draft, _dragging, _updatingProgress;
    private string _page = "library";
    private GlobalHotkeys? _hotkeys;
    private MediaPlayer? _media;
    private CancellationTokenSource? _previewCancel, _launchCancel;
    private PlaybackEngine? _engine;
    private WindowsKeySink? _sink;
    private bool _previewActive, _previewPaused, _rendering;
    private double _position, _previewDuration;
    private string _prefsPath => Path.Combine(_store.DataDirectory, "preferences.json");
    private PlayOptions _previewOptions = new();
    private PlaybackPlan? _previewPlan;
    private readonly ShortcutLaunchGate _launchGate = new();
    private bool _gameHotkeyEnabled;
    private InstrumentProfile SelectedInstrument => InstrumentCatalog.Get((InstrumentCombo.SelectedItem as InstrumentChoice)?.Id ?? "windsong");
    private sealed record InstrumentChoice(InstrumentProfile Profile)
    {
        public string Id => Profile.Id;
        public string Name => Profile.Name;
        public string Detail => Profile.Layout + (Profile.CanAutoPlay ? "" : " · 暂不自动演奏");
        public Uri? IconSource => Profile.IconFile == null ? null : new Uri("pack://application:,,,/Assets/Instruments/" + Profile.IconFile);
    }
    private int _nativeAttempts; // Exposed only in validation evidence.

    public MainWindow(string? dataDirectory = null, bool uiTest = false, string? validationCatalog = null)
    {
        if (Environment.GetCommandLineArgs().Contains("--smart-interlude-validation")) EnsureSmartInterludeValidationIsolation(dataDirectory, uiTest, validationCatalog);
        if (validationCatalog != null && !uiTest) throw new InvalidOperationException("仅隔离自测可使用目录替代。");
        _uiTest = uiTest;
        InitializeComponent();
        if (_uiTest) { ShowActivated = false; ShowInTaskbar = false; }
        Width = Math.Min(1460, SystemParameters.WorkArea.Width); Height = Math.Min(940, SystemParameters.WorkArea.Height);
        _store = new LibraryStore(dataDirectory ?? Path.Combine(AppContext.BaseDirectory, "UserData"), validationCatalog ?? Path.Combine(AppContext.BaseDirectory, "Songs"));
        DataPathText.Text = _store.DataDirectory;
        InitializeLibraryControls();
        FilterCombo.SelectedIndex = ChinesePopularFilterIndex; SortCombo.SelectedIndex = ChinesePrioritySortIndex; ZoomCombo.SelectedIndex = 0;
        InstrumentCombo.ItemsSource = InstrumentCatalog.All.Select(p => new InstrumentChoice(p)).ToList();
        InstrumentCombo.SelectedIndex = 0;
        LoadPreferences();
        InitializeAppearance();
        BuildKeys();
        _timer.Tick += (_, _) => UpdatePlaybackView();
        _timer.Start();
        _ready = true;
        RefreshLibrary();
        var initialEntry = _store.Query(new(Filter: LibraryFilter.ChinesePopular, Sort: LibrarySort.ChinesePopular, Limit: 1)).Items.FirstOrDefault()
            ?? _store.Query(new(Limit: 1)).Items.FirstOrDefault();
        if (initialEntry != null) SelectEntry(initialEntry);
        SetPage("library");
        if (_store.LoadWarnings.Count > 0) Status(string.Join("；", _store.LoadWarnings));
    }
    private void Window_Loaded(object sender, RoutedEventArgs e)
    {
        if (!_uiTest)
        {
            _hotkeys = new GlobalHotkeys(new WindowInteropHelper(this).Handle, TogglePause, () => EmergencyStop("F9 紧急停止"), () => _ = ShortcutStartAsync());
            if (!_hotkeys.StopRegistered) { HotkeyHint.Text = "F9 被占用 · 游戏输出已禁用"; Status("F9 注册失败，游戏按键输出被禁用；请关闭占用热键的软件并重新启动琴伴。"); }
            else if (!_hotkeys.StartRegistered) { HotkeyHint.Text = "Shift+Enter 被占用 / F9 可停止"; Status("Shift+Enter 注册失败，无法启用快捷演奏；请关闭占用热键的软件后重新启动琴伴。"); }
            else if (!_hotkeys.PauseRegistered) { HotkeyHint.Text = "F8 被占用 / F9 可停止"; Status("F8 注册失败，暂停按钮仍可使用；F9 紧急停止已注册。"); }
        }
        RefreshTargets();
        if (_uiTest) _ = RunUiValidationAsync();
    }
    private void Window_Closed(object? sender, EventArgs e)
    {
        _closing = true; CancelLibraryQuery(); EmergencyStop("窗口关闭"); _timer.Stop(); _hotkeys?.Dispose();
        _media?.Close(); _sink?.Dispose();
        try { SavePreferences(); } catch (Exception ex) { ReportError(ex, "偏好未保存（保留原文件）"); }
    }
    private void Status(string message) { if (!_closing) { StatusText.Text = message; StatusText.ToolTip = message; } }
    private void ReportError(Exception ex, string prefix = "操作失败")
    {
        Status(prefix + "：" + ex.Message);
        if (!_uiTest) MessageBox.Show(this, ex.Message, "琴伴 · " + prefix, MessageBoxButton.OK, MessageBoxImage.Warning);
    }
    private void BuildKeys()
    {
        var instrument = SelectedInstrument;
        _keys.Clear(); KeysPanel.Children.Clear();
        KeysPanel.Rows = Math.Max(1, (instrument.Keys.Count + 6) / 7);
        InstrumentLabel.Text = instrument.Layout;
        Roll.Instrument = instrument;
        foreach (var item in instrument.Keys)
        {
            char key = item.Key;
            var content = new StackPanel();
            content.Children.Add(new TextBlock { Text = key.ToString(), FontSize = 16, FontFamily = new FontFamily("Segoe UI"), HorizontalAlignment = HorizontalAlignment.Center });
            content.Children.Add(new TextBlock { Text = item.Label, FontSize = 10, Foreground = (Brush)FindResource("MutedBrush"), HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 3, 0, 0) });
            var button = new Button { Content = content, Tag = key, Height = 44, Padding = new Thickness(3), Margin = new Thickness(3), Background = _normalKey, ToolTip = $"合成试听 {key} / {item.Label}（非游戏音色）" };
            System.Windows.Automation.AutomationProperties.SetName(button, $"试听键位 {key} / {item.Label}");
            button.Click += KeyPreview_Click; KeysPanel.Children.Add(button); _keys.Add(key, button);
        }
        Roll.InvalidateVisual();
    }
    private void Instrument_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_ready) return;
        EmergencyStop("乐器已切换，已按新键位重新适配"); _position = 0; BuildKeys();
        try { RebuildPlan(); SavePreferences(); } catch (Exception ex) { ReportError(ex, "乐器适配失败"); }
    }
    private void Nav_Click(object sender, RoutedEventArgs e) => SetPage((string)((Button)sender).Tag);
    private void SetPage(string page)
    {
        _page = page;
        Workbench.Visibility = page is "library" or "favorites" or "queue" ? Visibility.Visible : Visibility.Collapsed;
        EditorPage.Visibility = page == "editor" ? Visibility.Visible : Visibility.Collapsed;
        SettingsPage.Visibility = page == "settings" ? Visibility.Visible : Visibility.Collapsed;
        HelpPage.Visibility = page == "help" ? Visibility.Visible : Visibility.Collapsed;
        AppearancePage.Visibility = page == "appearance" ? Visibility.Visible : Visibility.Collapsed;
        ParameterOverlay.Visibility = Visibility.Collapsed; ParametersToggle.Content = "演奏调校";
        RefreshNavigationAppearance();
        PageTitle.Text = page switch { "favorites" => "收藏", "queue" => "播放队列", "editor" => "谱子工坊", "appearance" => "外观背景", "settings" => "安全设置", "help" => "使用指南", _ => "我的曲库" };
        PageSubtitle.Text = page switch { "editor" => "写一段旋律，或修改自己的谱子。", "appearance" => "选择一张喜欢的图片，让音乐有自己的氛围。", "settings" => "目标窗口、演奏授权和本地数据。", "help" => "从选曲到游戏演奏。", "queue" => "连续试听，不自动触发游戏演奏。", "favorites" => "喜欢的旋律，随时再听。", _ => "默认展示中文流行；全部语言可查看其它来源。" };
        if (page == "editor" && string.IsNullOrWhiteSpace(EditorBox.Text)) NewScore_Click(this, new());
        if (page == "settings") RefreshTargets();
        RefreshLibrary();
    }
    private void Song_Selected(object sender, SelectionChangedEventArgs e)
    {
        if (_ready && !_loadingOptions && SongList.SelectedItem is LibraryEntry entry) SelectEntry(entry);
    }
    private void SelectEntry(LibraryEntry entry)
    {
        EmergencyStop("已切换曲谱");
        _selected = entry; _song = null; _draft = false; _position = 0;
        NowTitle.Text = entry.Title; NowTitle.ToolTip = entry.Title; FooterTitle.Text = entry.Title;
        ShowSongMetadata(entry.Provenance, entry.Author, entry.Category);
        SourceText.Text = "正在准备曲谱…\n" + ProvenanceSummary(); SourceText.ToolTip = SourceText.Text;
        FavoriteButton.Content = entry.FavoriteText; QueueButton.Content = entry.QueueText;
        _loadingOptions = true;
        try { SongList.SelectedItem = entry; LoadOptions(entry.Options); TracksPanel.Children.Clear(); }
        finally { _loadingOptions = false; }
        var options = entry.Options.Copy(); options.InstrumentId = SelectedInstrument.Id;
        QueuePreparation(() => _store.LoadSong(entry), options, true, false);
    }
    private void LoadOptions(PlayOptions options)
    {
        SpeedSlider.Value = options.Speed; TransposeSlider.Value = options.Transpose; OctaveSlider.Value = options.Octave;
        ChordCombo.SelectedIndex = (int)options.Chords; ChordLimitSlider.Value = options.MaxChordNotes; StrumSlider.Value = options.StrumMs; HoldSlider.Value = options.HoldMs; HoldByScoreCheck.IsChecked = options.HoldByScore; NativeChordCheck.IsChecked = options.NativeGuitarChords;
        AccidentalCombo.SelectedIndex = (int)options.Accidentals; RangeCombo.SelectedIndex = (int)options.Range;
        ExcludeDrums.IsChecked = options.ExcludePercussion; LoopCheck.IsChecked = options.Loop;
        SmartInterludesCheck.IsChecked = SmartInterludeArranger.IsEnabled(
            _song ?? new SongDocument { Provenance = _selected?.Provenance ?? new() }, options);
        LoopStartBox.Text = (options.LoopStartMs / 1000).ToString("0.###", CultureInfo.InvariantCulture); LoopEndBox.Text = (options.LoopEndMs / 1000).ToString("0.###", CultureInfo.InvariantCulture);
        UpdateParameterLabels();
    }
    private PlayOptions ReadOptions()
    {
        if (!double.TryParse(LoopStartBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double start) || !double.TryParse(LoopEndBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double end)) throw new FormatException("循环起止时间须是秒数，例如 12.5。");
        var options = new PlayOptions
        {
            InstrumentId = SelectedInstrument.Id, HoldByScore = HoldByScoreCheck.IsChecked == true, NativeGuitarChords = NativeChordCheck.IsChecked == true,
            Speed = SpeedSlider.Value, Transpose = (int)TransposeSlider.Value, Octave = (int)OctaveSlider.Value,
            Chords = (ChordMode)Math.Max(0, ChordCombo.SelectedIndex), MaxChordNotes = (int)ChordLimitSlider.Value,
            StrumMs = (int)StrumSlider.Value, HoldMs = (int)HoldSlider.Value,
            Accidentals = (AccidentalMode)Math.Max(0, AccidentalCombo.SelectedIndex), Range = (RangeMode)Math.Max(0, RangeCombo.SelectedIndex),
            ExcludePercussion = ExcludeDrums.IsChecked == true, SmartInterludes = SmartInterludesCheck.IsChecked == true,
            Loop = LoopCheck.IsChecked == true, LoopStartMs = start * 1000, LoopEndMs = end * 1000,
            Tracks = TracksPanel.Children.OfType<CheckBox>().Where(c => c.IsChecked == true).Select(c => (int)c.Tag).ToList()
        };
        options.Validate();
        if (_song != null && options.Loop && end > 0 && (end <= start || end * 1000 > _song.DurationMs + 1)) throw new FormatException("循环终点须大于起点且不超过原谱总时长。");
        if (_song != null && options.Loop && start * 1000 >= _song.DurationMs) throw new FormatException("循环起点须小于原谱总时长。");
        return options;
    }
    private void UpdateParameterLabels()
    {
        SpeedLabel.Text = $"{SpeedSlider.Value:0.00}×"; TransposeLabel.Text = $"{TransposeSlider.Value:+0;-0;0}";
        OctaveLabel.Text = $"{OctaveSlider.Value:+0;-0;0}"; ChordLimitLabel.Text = $"{ChordLimitSlider.Value:0} 音";
        StrumLabel.Text = $"{StrumSlider.Value:0} ms"; HoldLabel.Text = $"{HoldSlider.Value:0} ms";

        if (_song != null) BpmBox.Text = (_song.Bpm * SpeedSlider.Value).ToString("0.#", CultureInfo.InvariantCulture);
    }
    private void RebuildPlan(bool save = true)
    {
        // Parameters may change while a new source is loading. Keep the current controls, not old entry options.
        var song = _song;
        ClearReadyPlan();
        var options = ReadOptions();
        if (song == null)
        {
            if (_selected == null) return;
            options.Tracks = _selected.Options.Tracks?.ToList();
            var entry = _selected; QueuePreparation(() => _store.LoadSong(entry), options, true, save);
        }
        else QueuePreparation(() => song, options, false, save);
    }
    private void ApplyReadyPlan(PreparedScore prepared)
    {
        _plan = prepared.Plan; _preparedOptions = prepared.Options; UpdateParameterLabels();
        Roll.Plan = _plan; Roll.PositionMs = _position; Roll.InvalidateVisual();
        ConversionText.Text = _plan.Report.Summary; AdaptationExpander.IsExpanded = _plan.Notes.Count == 0;
        WarningsText.Text = _plan.Warnings.Count > 0 ? string.Join("\n", _plan.Warnings) : "自然音适配已完成。试听与游戏音色不同，演奏效果仍需游戏内确认。";
        SourceText.Text = _song!.Source + "\n" + _song.Description + "\n" + ProvenanceSummary(); SourceText.ToolTip = SourceText.Text;
        SongStats.Text = $"{_song.Bpm:0.#} BPM  ·  {_song.Notes.Count} 音  ·  {prepared.Tracks.Count} 轨 · 已准备";
        DurationLabel.Text = FormatTime(_plan.DurationMs);
        _updatingProgress = true;
        try { ProgressSlider.Maximum = Math.Max(1, _plan.DurationMs); _position = Math.Clamp(_position, 0, _plan.DurationMs); ProgressSlider.Value = _position; }
        finally { _updatingProgress = false; }
        PreviewButton.IsEnabled = _plan.Notes.Count > 0;
        GameButton.IsEnabled = !_song.Provenance.Synthetic && _selected?.Provenance.Synthetic != true && (_gameHotkeyEnabled || (_plan.Notes.Count > 0 && SelectedInstrument.CanAutoPlay));
        NativeChordCheck.IsEnabled = SelectedInstrument.Keys.Any(k => k.IsChord);
    }
    private void ParametersChanged()
    {
        if (!_ready || _loadingOptions || (_song == null && _selected == null)) return;
        EmergencyStop("参数已修改，请重新试听或演奏"); _position = 0;
        try { RebuildPlan(); } catch (Exception ex) { ReportError(ex, "参数无效"); }
    }
    private void Parameter_Changed(object sender, RoutedPropertyChangedEventArgs<double> e) => ParametersChanged();
    private void Option_Changed(object sender, SelectionChangedEventArgs e) => ParametersChanged();
    private void Option_Checked(object sender, RoutedEventArgs e) => ParametersChanged();
    private void Loop_Changed(object sender, RoutedEventArgs e) => ParametersChanged();
    private void Reset_Click(object sender, RoutedEventArgs e)
    {
        _loadingOptions = true; LoadOptions(new()); foreach (var c in TracksPanel.Children.OfType<CheckBox>()) c.IsChecked = true; _loadingOptions = false; ParametersChanged();
    }
    private void Bpm_Click(object sender, RoutedEventArgs e)
    {
        if (_song == null) return;
        if (!double.TryParse(BpmBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double target) || !double.IsFinite(target) || target / _song.Bpm is < .25 or > 3) { ReportError(new FormatException("目标 BPM 超出本曲 0.25–3 倍范围。")); return; }
        SpeedSlider.Value = Math.Round(target / _song.Bpm, 3);
    }
    private void Favorite_Click(object sender, RoutedEventArgs e)
    {
        if (_selected == null) return;
        try { _selected.Favorite = !_selected.Favorite; _store.Save(_selected); FavoriteButton.Content = _selected.FavoriteText; RefreshLibrary(); Status(_selected.Favorite ? "已加入收藏" : "已取消收藏"); }
        catch (Exception ex) { FavoriteButton.Content = _selected.FavoriteText; ReportError(ex, "收藏未保存"); }
    }
    private void Queue_Click(object sender, RoutedEventArgs e)
    {
        if (_selected == null) return;
        try { _selected.InQueue = !_selected.InQueue; _store.Save(_selected); QueueButton.Content = _selected.QueueText; RefreshLibrary(); Status(_selected.InQueue ? "已加入试听队列" : "已移出试听队列"); }
        catch (Exception ex) { QueueButton.Content = _selected.QueueText; ReportError(ex, "队列未保存"); }
    }
    private void Zoom_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_ready) return; Roll.WindowSeconds = ZoomCombo.SelectedIndex switch { 1 => 40, 2 => 0, _ => 20 }; Roll.InvalidateVisual();
    }
    private void LoadPreferences()
    {
        if (!File.Exists(_prefsPath)) return;
        var prefs = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(_prefsPath), JsonDefaults.Options) ?? throw new FormatException("偏好文件无效；已保留原文件。");
        if (!double.IsFinite(prefs.Volume) || prefs.Volume is < 0 or > 1) throw new FormatException("音量偏好无效，已保留原文件。");
        VolumeSlider.Value = prefs.Volume; QueueAutoCheck.IsChecked = prefs.QueueAuto;
        _appearance = prefs.Appearance?.Copy() ?? new();
        _appearance.Validate();
        _ = InstrumentCatalog.Get(prefs.InstrumentId);
        InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == prefs.InstrumentId);
    }
    private void SavePreferences()
    {
        if (_store == null) return;
        string temp = _prefsPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(new Preferences(VolumeSlider.Value, QueueAutoCheck.IsChecked == true, SelectedInstrument.Id, _appearance.Copy()), JsonDefaults.Options));
        File.Move(temp, _prefsPath, true);
    }
    private record Preferences(double Volume = .65, bool QueueAuto = false, string InstrumentId = "windsong", AppearanceSettings? Appearance = null);
    private static string FormatTime(double milliseconds) { var time = TimeSpan.FromMilliseconds(Math.Max(0, milliseconds)); return time.ToString(time.TotalHours >= 1 ? @"h\:mm\:ss" : @"mm\:ss"); }
}
