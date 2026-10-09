using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private readonly ScorePreparer _scorePreparer = new();
    private Task _prepareTask = Task.CompletedTask;
    private CancellationTokenSource? _prepareCancel;
    private int _prepareEpoch;
    private bool _preparing;
    private PlayOptions? _preparedOptions;
    private PreparedScore? _lastPreparedScore;
    private void ClearReadyPlan()
    {
        _plan = null; _preparedOptions = null; _lastPreparedScore = null; Roll.Plan = null; Roll.InvalidateVisual();
        PreviewButton.IsEnabled = false; GameButton.IsEnabled = _gameHotkeyEnabled;
    }
    private void CancelScorePreparation()
    {
        ++_prepareEpoch; _prepareCancel?.Cancel();
        if (_preparing)
        {
            _preparing = false; ClearReadyPlan(); SongStats.Text = "准备已取消 · 重新选择或调整参数";
        }
    }
    private void QueuePreparation(Func<SongDocument> loader, PlayOptions options, bool loadSelection, bool save)
    {
        _prepareCancel?.Cancel(); int epoch = ++_prepareEpoch;
        var cancel = new CancellationTokenSource(); _prepareCancel = cancel; _preparing = true;
        ClearReadyPlan(); SongStats.Text = "正在准备曲谱… · 未就绪时不会排队开播"; ModeLabel.Text = "正在准备 · 播放暂不可用";
        _prepareTask = PrepareAndApplyAsync(loader, options, loadSelection, save, epoch, cancel, _selected, _draft);
    }
    private async Task PrepareAndApplyAsync(Func<SongDocument> loader, PlayOptions options, bool loadSelection,
        bool save, int epoch, CancellationTokenSource cancel, LibraryEntry? selected, bool draft)
    {
        try
        {
            var prepared = await _scorePreparer.PrepareAsync(loader, options, cancel.Token);
            if (_closing || cancel.IsCancellationRequested || epoch != _prepareEpoch || selected != _selected || draft != _draft) return;
            _song = prepared.Song; _lastPreparedScore = prepared;
            if (loadSelection)
            {
                _loadingOptions = true;
                try
                {
                    LoadOptions(prepared.Options); TracksPanel.Children.Clear();
                    foreach (var track in prepared.Tracks)
                    {
                        var check = new CheckBox { Content = $"{track.Name} · {track.NoteCount} 音", Tag = track.Id,
                            IsChecked = prepared.Options.Tracks == null || prepared.Options.Tracks.Contains(track.Id), FontSize = 12, Margin = new Thickness(0, 4, 0, 4) };
                        check.Checked += Option_Checked; check.Unchecked += Option_Checked; TracksPanel.Children.Add(check);
                    }
                    SongList.SelectedItem = selected;
                }
                finally { _loadingOptions = false; }
                NowTitle.Text = _song.Title; NowTitle.ToolTip = _song.Title; FooterTitle.Text = _song.Title;
            }
            ShowSongMetadata(_song.Provenance, _song.Author, _song.Category);
            if (save && selected != null && !draft) { selected.Options = prepared.Options.Copy(); _store.Save(selected); }
            _preparing = false; ApplyReadyPlan(prepared); ModeLabel.Text = "已准备 · " + (_gameHotkeyEnabled ? "游戏前台 Shift+Enter 开始" : "安全模式 · 仅本地试听");
            Status("已准备 · " + _song.Title + "；先试听再进入游戏。");
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            if (!_closing && epoch == _prepareEpoch)
            {
                _preparing = false; ClearReadyPlan(); SongStats.Text = "准备失败 · 不可演奏";
                ReportError(ex, loadSelection ? "载入谱子失败" : "曲谱适配失败");
            }
        }
        finally
        {
            if (ReferenceEquals(_prepareCancel, cancel)) _prepareCancel = null;
            cancel.Dispose();
        }
    }
    private async Task WaitForPreparationAsync()
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed < TimeSpan.FromSeconds(30))
        {
            var task = _prepareTask;
            var remaining = TimeSpan.FromSeconds(30) - watch.Elapsed;
            if (remaining <= TimeSpan.Zero) break;
            await task.WaitAsync(remaining);
            if (ReferenceEquals(task, _prepareTask) && !_preparing) return;
        }
        throw new TimeoutException("曲谱准备未在 30 秒内结束。");
    }
}
