using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private int _previewEpoch;
    private string? _previewFile;
    private readonly List<string> _previewCleanupWarnings = [];
    private void DeleteOwnedPreview(string? path)
    {
        if (path == null) return;
        string folder = Path.GetFullPath(Path.Combine(_store.DataDirectory, "preview"));
        if (!string.Equals(Path.GetDirectoryName(Path.GetFullPath(path)), folder, StringComparison.OrdinalIgnoreCase) ||
            !Guid.TryParseExact(Path.GetFileNameWithoutExtension(path), "N", out _) || Path.GetExtension(path) != ".wav")
            throw new InvalidOperationException("拒绝清理非本次生成的试听文件。");
        try { File.Delete(path); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            string warning = "试听临时文件未清理：" + Path.GetFileName(path) + "：" + ex.Message;
            _previewCleanupWarnings.Add(warning); Status(warning);
        }
    }
    public void EmergencyStop(string reason = "手动停止")
    {
        CancelScorePreparation(); ++_previewEpoch; var renderingCancel = _previewCancel; _previewCancel = null; renderingCancel?.Cancel(); _launchCancel?.Cancel(); _launchGate.Cancel(); _engine?.Stop(reason);
        _media?.Stop(); _media?.Close(); _media = null; var oldPreviewFile = _previewFile; _previewFile = null; DeleteOwnedPreview(oldPreviewFile); _previewActive = false; _previewPaused = false; _rendering = false;
        if (ModeLabel != null) { ModeLabel.Text = "安全模式 · 仅本地试听"; PauseButton.Content = "暂停"; Status(reason); }
        foreach (var button in _keys.Values) button.Background = _normalKey;
    }
    private void Preview_Click(object sender, RoutedEventArgs e) => _ = StartPreviewAsync();
    private async Task StartPreviewAsync(PlaybackPlan? specific = null)
    {
        if (specific == null && (_preparing || _plan == null || _preparedOptions == null)) { Status("曲谱尚未准备就绪，请准备完成后再次点击试听。"); return; }
        if (_song == null && specific == null) return;
        CancellationTokenSource? cancel = null; string? ownedPath = null; int epoch = -1;
        try
        {
            double seek = _position; EmergencyStop("正在生成试听音频…"); epoch = _previewEpoch;
            var plan = specific ?? _plan;
            if (plan == null || plan.Notes.Count == 0) throw new InvalidOperationException("没有可试听音符，请检查轨道和适配设置。");
            _previewOptions = specific == null ? _preparedOptions!.Copy() : new(); _previewPlan = plan;
            if (_previewOptions.Loop && _previewOptions.LoopStartMs / _previewOptions.Speed >= PreviewAudio.MaxPreviewMs) throw new InvalidOperationException("循环起点超出本地试听前 10 分钟上限；请调整循环段。游戏演奏上限仍为 30 分钟。");
            if (seek >= plan.DurationMs - 30) seek = 0;
            cancel = new CancellationTokenSource(); _previewCancel = cancel; _rendering = true;
            ModeLabel.Text = "本地试听 · 按谱时值的合成音（非游戏音色）";
            string folder = Path.Combine(_store.DataDirectory, "preview"); Directory.CreateDirectory(folder);
            string path = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".wav");
            ownedPath = path;
            double duration = await Task.Run(() => PreviewAudio.WriteWave(plan, path, cancel.Token));
            if (cancel.IsCancellationRequested || _closing || epoch != _previewEpoch || !ReferenceEquals(_previewCancel, cancel)) return;
            _previewFile = path; ownedPath = null;
            _rendering = false; _previewDuration = duration;
            var media = new MediaPlayer { Volume = VolumeSlider.Value }; _media = media;
            media.MediaOpened += (_, _) =>
            {
                if (!ReferenceEquals(_media, media) || epoch != _previewEpoch || _closing) return;
                _previewActive = true; _previewPaused = false;
                var options = _previewOptions;
                _position = specific != null ? 0 : options.Loop ? options.LoopStartMs / options.Speed : Math.Min(seek, Math.Max(0, duration - 500));
                media.Position = TimeSpan.FromMilliseconds(_position); media.Play();
                if (specific == null && _selected != null && !_draft)
                {
                    try { _selected.LastPlayedAt = DateTimeOffset.Now; _store.Save(_selected); }
                    catch (Exception ex) { EmergencyStop("播放记录保存失败"); ReportError(ex, "试听失败"); return; }
                }
                Status(duration >= PreviewAudio.MaxPreviewMs ? "本地试听中 · 超长谱子只试听前 10 分钟" : "本地试听中 · 没有发送游戏按键");
            };
            media.MediaFailed += (_, e) => { if (ReferenceEquals(_media, media)) { EmergencyStop("试听设备或音频加载失败"); ReportError(e.ErrorException, "试听失败"); } };
            media.MediaEnded += (_, _) =>
            {
                if (!ReferenceEquals(_media, media)) return;
                var options = _previewOptions;
                if (specific == null && options.Loop) { _position = options.LoopStartMs / options.Speed; media.Position = TimeSpan.FromMilliseconds(_position); media.Play(); return; }
                _previewActive = false; _previewPaused = false; _position = specific != null ? 0 : plan.DurationMs; PauseButton.Content = "暂停"; media.Close(); _media = null; var completedFile = _previewFile; _previewFile = null; DeleteOwnedPreview(completedFile); Status("试听完成");
                if (specific == null && QueueAutoCheck.IsChecked == true) MoveSong(1, true, true);
            };
            media.Open(new Uri(path));
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { _rendering = false; ReportError(ex, "试听失败"); }
    }
    private void KeyPreview_Click(object sender, RoutedEventArgs e)
    {
        char key = (char)((Button)sender).Tag;
        var item = SelectedInstrument.Keys.Single(k => k.Key == key);
        var note = new PlannedNote(item.Pitches[0], key, 0, 65, 650, 100, 0, item.IsChord ? item.Pitches : null, SelectedInstrument.SupportsSustain);
        _ = StartPreviewAsync(new([note], 700, new(1, 1, 0, 0, 0, 0, 0), []));
    }
    private void Pause_Click(object sender, RoutedEventArgs e) => TogglePause();
    private void TogglePause()
    {
        if (_engine?.IsRunning == true)
        {
            _engine.TogglePause(); PauseButton.Content = _engine.IsPaused ? "继续" : "暂停";
            Status(_engine.IsPaused ? "游戏演奏暂停；继续需仍处于原神前台" : "游戏演奏继续");
        }
        else if (_previewActive && _media != null)
        {
            _previewPaused = !_previewPaused;
            if (_previewPaused) _media.Pause(); else _media.Play();
            PauseButton.Content = _previewPaused ? "继续" : "暂停"; Status(_previewPaused ? "本地试听已暂停" : "本地试听继续");
        }
    }
    private void Stop_Click(object sender, RoutedEventArgs e) => EmergencyStop();
    private void Game_Click(object sender, RoutedEventArgs e)
    {
        // Neither game consent nor a fake shortcut may bypass this test-only native-output lock.
        if (_uiTest) { Status("自动化验证模式：拒绝所有真实游戏按键输出"); return; }
        if (_gameHotkeyEnabled)
        {
            _gameHotkeyEnabled = false; EmergencyStop("快捷演奏已关闭"); GameButton.Content = "启用快捷演奏"; return;
        }
        if (_hotkeys?.StopRegistered != true || !_hotkeys.StartRegistered) { ReportError(new InvalidOperationException("F9 或 Shift+Enter 未注册，禁止启用游戏按键。")); return; }
        if (GameConsent.IsChecked != true) { SetPage("settings"); Status("请先阅读风险并勾选本次会话的演奏确认。"); return; }
        if (TargetCombo.SelectedItem is not GameWindow target) { SetPage("settings"); RefreshTargets(); Status("请启动原神并选定目标窗口，再启用快捷演奏。"); return; }
        try
        {
            if (_song == null) return;
            ScorePlaybackPolicy.EnsureRealInputAllowed(_song, _selected);
            if (_preparing || _preparedOptions == null) throw new InvalidOperationException("曲谱尚未准备就绪，请准备完成后重新启用；不会等待后自动开播。");
            if (_plan?.Notes.Count is not > 0 || !SelectedInstrument.CanAutoPlay) throw new InvalidOperationException("此谱或此乐器目前不可自动演奏。");
            string summary = $"目标：{target.Title}\n当前曲谱：{_song.Title}\n乐器：{SelectedInstrument.Name}\n{_plan.Report.Summary}\n\n启用本次会话的快捷演奏：你主动选择歌曲和乐器后，在选定原神前台按 Shift+Enter，松开这两个键即开始，无倒计时。\n\n请先打开对应乐器、关闭聊天。程序无法判断游戏内部是否仍在聊天/菜单。F9 停止；此按钮可关闭授权。不会自动开始下一首。";
            if (MessageBox.Show(this, summary, "启用 Shift+Enter 快捷演奏", MessageBoxButton.OKCancel, MessageBoxImage.Warning) != MessageBoxResult.OK) return;
            EmergencyStop("已启用：选好歌曲 → 游戏前台 → Shift+Enter，松键即开始");
            _gameHotkeyEnabled = true; GameButton.Content = "关闭快捷演奏"; ModeLabel.Text = "快捷演奏已启用 · Shift+Enter 开始 / F9 停止";
        }
        catch (Exception ex) { ReportError(ex, "无法启用快捷演奏"); }
    }
    private async Task ShortcutStartAsync()
    {
        if (_uiTest) { Status("自动化验证模式：拒绝快捷键真实输出"); return; }
        if (_preparing || _preparedOptions == null) { Status("曲谱尚未准备就绪，请准备完成后重新按 Shift+Enter；不会排队开播。"); return; }
        if (_launchCancel != null || _engine?.IsRunning == true) return;
        if (!_gameHotkeyEnabled || GameConsent.IsChecked != true || _song == null || _plan == null || _plan.Notes.Count == 0)
        { Status("请先选谱、选乐器，并启用本次会话的快捷演奏。"); return; }
        if (TargetCombo.SelectedItem is not GameWindow target) { Status("快捷演奏未开始：没有选定原神窗口"); return; }
        try { ScorePlaybackPolicy.EnsureRealInputAllowed(_song, _selected); }
        catch (Exception ex) { Status(ex.Message); return; }
        var plan = _plan;
        PlayOptions options;
        try { options = _preparedOptions.Copy(); } catch (Exception ex) { Status("快捷演奏参数无效：" + ex.Message); return; }
        var initial = GameWindows.ReadShortcutState(target, true, _hotkeys?.StopRegistered == true, _hotkeys?.StartRegistered == true, false);
        if (!initial.TargetForeground || initial.OtherModifierDown || !initial.StopRegistered || !initial.StartRegistered)
        { Status("快捷演奏未开始：目标须为选定的原神前台，且 Ctrl/Alt/Win 已松开、热键已注册。"); return; }
        double seek = _position >= plan.DurationMs - 30 ? 0 : _position;
        EmergencyStop("等待松开 Shift 和 Enter…");
        var launch = new CancellationTokenSource(); _launchCancel = launch;
        try
        {
            var decision = _launchGate.Request(initial);
            while (decision == ShortcutDecision.WaitForRelease)
            {
                await Task.Delay(8, launch.Token); // Only physical key release, NOT a countdown.
                bool authorized = _gameHotkeyEnabled && GameConsent.IsChecked == true && ReferenceEquals(_plan, plan)
                    && TargetCombo.SelectedItem is GameWindow current && current.Handle == target.Handle && current.ProcessId == target.ProcessId;
                decision = _launchGate.Poll(GameWindows.ReadShortcutState(target, authorized, _hotkeys?.StopRegistered == true, _hotkeys?.StartRegistered == true, _engine?.IsRunning == true));
            }
            launch.Token.ThrowIfCancellationRequested();
            if (decision != ShortcutDecision.Start) { Status("快捷演奏已取消：" + _launchGate.Reason); return; }
            var guard = GameWindows.Check(target); if (!guard.Allowed) throw new InvalidOperationException(guard.Reason);
            var sink = new WindowsKeySink(target, options.InstrumentId); _sink = sink; sink.Arm();
            var engine = new PlaybackEngine(sink, () => GameWindows.Check(target)); _engine = engine;
            if (_selected != null && !_draft) { _selected.LastPlayedAt = DateTimeOffset.Now; _store.Save(_selected); }
            ModeLabel.Text = "游戏演奏 · " + SelectedInstrument.Name + " · F9 停止";
            Status("演奏中 · 保留原谱时值，仅向选定原神前台发送当前乐器键位");
            var result = await engine.PlayAsync(plan, options, seek);
            _nativeAttempts += sink.SendAttempts; sink.Dispose();
            if (ReferenceEquals(_engine, engine) && !_closing)
            {
                ModeLabel.Text = _gameHotkeyEnabled ? "快捷已启用 · Shift+Enter 可再次开始" : "安全模式 · 仅本地试听"; PauseButton.Content = "暂停";
                Status(result.Reason + (sink.ReleaseError != null ? "；释放失败：" + sink.ReleaseError + "，请手动松键并检查权限。" : "；已请求释放按键"));
            }
        }
        catch (OperationCanceledException) { Status("快捷启动已取消，未继续按键输出"); }
        catch (Exception ex)
        {
            _sink?.Dispose(); ModeLabel.Text = _gameHotkeyEnabled ? "快捷已启用 · 当前播放已中断" : "安全模式 · 仅本地试听";
            // Do not show a modal dialog or steal game focus from a global shortcut.
            Status("游戏演奏未开始或已中断：" + ex.Message);
        }
        finally { _launchGate.Cancel(); if (ReferenceEquals(_launchCancel, launch)) _launchCancel = null; launch.Dispose(); }
    }
    private void GameAuthorization_Changed(object sender, RoutedEventArgs e)
    {
        if (!_ready) return;
        _gameHotkeyEnabled = false; EmergencyStop("游戏窗口或风险授权已变化，请重新启用快捷演奏"); GameButton.Content = "启用快捷演奏";
    }
    private void UpdatePlaybackView()
    {
        if (_closing || _plan == null) return;
        PreviewButton.Content = _rendering ? "生成中…" : "本地试听";
        if (_rendering) return;
        if (_engine?.IsRunning == true) _position = _engine.PositionMs;
        else if (_previewActive && _media != null)
        {
            _position = _media.Position.TotalMilliseconds;
            var options = _previewOptions;
            double end = options.Loop && options.LoopEndMs > options.LoopStartMs ? Math.Min(_previewDuration, options.LoopEndMs / options.Speed) : _previewDuration;
            if (options.Loop && _position >= end - 15) { _position = options.LoopStartMs / options.Speed; _media.Position = TimeSpan.FromMilliseconds(_position); }
        }
        if (!_dragging) { _updatingProgress = true; ProgressSlider.Value = _position; _updatingProgress = false; }
        PositionLabel.Text = FormatTime(_position);
        Roll.PositionMs = _position; Roll.InvalidateVisual();
        bool active = _engine?.IsRunning == true && !_engine.IsPaused || _previewActive && !_previewPaused;
        var lit = active ? (_previewActive ? _previewPlan ?? _plan : _plan).Notes.Where(n => n.StartMs <= _position && n.StartMs + Math.Max(n.HoldMs, 140) > _position).Select(n => n.Key).ToHashSet() : [];
        foreach (var (key, button) in _keys) button.Background = lit.Contains(key) ? _activeKey : _normalKey;
    }
    private void Progress_MouseDown(object sender, MouseButtonEventArgs e) => _dragging = true;
    private void Progress_MouseUp(object sender, MouseButtonEventArgs e) { _dragging = false; SeekTo(ProgressSlider.Value); }
    private void Progress_Changed(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (_ready && !_updatingProgress) SeekTo(e.NewValue);
    }
    private void SeekTo(double position)
    {
        if (_engine?.IsRunning == true || _launchCancel != null || _launchGate.Pending) EmergencyStop("进度已修改，游戏演奏需再次按 Shift+Enter");
        _position = position;
        if (_previewActive && _media != null) _media.Position = TimeSpan.FromMilliseconds(Math.Min(position, Math.Max(0, _previewDuration - 1)));
    }
    private void Volume_Changed(object sender, RoutedPropertyChangedEventArgs<double> e) { if (_media != null) _media.Volume = e.NewValue; }
    private void Previous_Click(object sender, RoutedEventArgs e) => MoveSong(-1, _previewActive, false);
    private void Next_Click(object sender, RoutedEventArgs e) => MoveSong(1, _previewActive, false);
    private Task _navigationTask = Task.CompletedTask;
    private int _navigationEpoch;
    private void MoveSong(int direction, bool preview, bool autoQueue) => _navigationTask = MoveSongAsync(direction, preview, autoQueue);
    private async Task MoveSongAsync(int direction, bool preview, bool autoQueue)
    {
        int epoch = ++_navigationEpoch;
        var query = autoQueue ? new LibraryQuery(Queue: true) : CurrentLibraryQuery();
        var selected = _selected;
        try
        {
            var result = await Task.Run(() =>
            {
                int total = _store.Query(query with { Offset = 0, Limit = 1 }).Total;
                if (total == 0) return (Entry: (LibraryEntry?)null, Position: -1, Finished: false);
                int position = selected == null ? -1 : _store.FindPosition(query, selected);
                int next = position < 0 ? (direction > 0 ? 0 : total - 1) : position + direction;
                if (autoQueue && next >= total) return (Entry: (LibraryEntry?)null, Position: -1, Finished: true);
                next = (next % total + total) % total;
                return (Entry: _store.Query(query with { Offset = next, Limit = 1 }).Items.FirstOrDefault(), Position: next, Finished: false);
            });
            if (_closing || epoch != _navigationEpoch || _selected != selected || (!autoQueue && CurrentLibraryQuery() != query)) return;
            if (result.Entry == null) { Status(result.Finished ? "队列试听完成" : "队列或当前列表为空"); return; }
            if (!autoQueue) { _libraryOffset = result.Position / LibraryPageSize * LibraryPageSize; }
            SelectEntry(result.Entry); RefreshLibrary(); await WaitForLibraryAsync(); await WaitForPreparationAsync();
            if (preview && !_closing && epoch == _navigationEpoch && _selected == result.Entry) await StartPreviewAsync();
        }
        catch (Exception ex) { if (!_closing) ReportError(ex, "切换曲谱失败"); }
    }
    private void RefreshTargets()
    {
        var selected = TargetCombo.SelectedItem as GameWindow;
        try
        {
            var list = GameWindows.List(); TargetCombo.ItemsSource = list;
            TargetCombo.SelectedItem = list.FirstOrDefault(w => w.Handle == selected?.Handle) ?? list.FirstOrDefault();
            TargetCombo.ToolTip = list.Count == 0 ? "未检测到原神可见窗口；试听仍可使用" : "只会向选定且处于前台的窗口发送按键";
        }
        catch (Exception ex) { ReportError(ex, "枚举原神窗口失败"); }
    }
    private void RefreshTargets_Click(object sender, RoutedEventArgs e) { RefreshTargets(); Status($"检测到 {TargetCombo.Items.Count} 个原神窗口"); }
}
