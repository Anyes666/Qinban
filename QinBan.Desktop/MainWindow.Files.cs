using System.Diagnostics;
using System.IO;
using System.Windows;
using Microsoft.Win32;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "选择本地谱子（不会上传）", Filter = "支持的谱子|*.mid;*.midi;*.txt;*.json|所有文件|*.*", Multiselect = true };
        if (dialog.ShowDialog(this) == true) await ImportFilesAsync(dialog.FileNames);
    }
    private async void ImportFolder_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "选择谱子文件夹（仅导入当前层，不递归扫描）" };
        if (dialog.ShowDialog(this) == true)
        {
            var extensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".mid", ".midi", ".txt", ".json" };
            await ImportFilesAsync(Directory.GetFiles(dialog.FolderName).Where(p => extensions.Contains(Path.GetExtension(p))).ToArray());
        }
    }
    private async void Window_Drop(object sender, DragEventArgs e)
    {
        if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
        e.Handled = true;
        var paths = (string[])e.Data.GetData(DataFormats.FileDrop);
        if (paths.Length == 1 && BackgroundImageLoader.SupportedExtension(paths[0])) await ImportBackgroundAsync(paths[0]);
        else await ImportFilesAsync(paths);
    }
    private async Task ImportFilesAsync(IEnumerable<string> files)
    {
        // Import writes only our data directory; parsing/copy are synchronous per file to avoid index races.
        var paths = files.ToList();
        if (paths.Count > 200) { ReportError(new FormatException("每批最多 200 个文件，请分批导入。")); return; }
        int success = 0, duplicate = 0; var errors = new List<string>(); LibraryEntry? last = null;
        ImportButton.IsEnabled = false;
        try
        {
            foreach (string path in paths)
            {
                Status($"正在导入 {success + duplicate + errors.Count + 1}/{paths.Count} · {Path.GetFileName(path)}");
                await Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.Background);
                try { var imported = _store.Import(path); if (imported.Duplicate) duplicate++; else success++; last = imported.Entry; }
                catch (Exception ex) { errors.Add(Path.GetFileName(path) + "：" + ex.Message); }
            }
            SetPage("library"); FilterCombo.SelectedIndex = 0; SearchBox.Clear(); RefreshLibrary(); if (last != null) SelectEntry(last);
            Status($"导入完成：新增 {success}，重复 {duplicate}，失败 {errors.Count}。原文件未修改。");
            if (errors.Count > 0 && !_uiTest) MessageBox.Show(this, string.Join("\n", errors), "部分文件导入失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally { ImportButton.IsEnabled = true; }
    }
    private void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_song == null) return;
        var dialog = new SaveFileDialog { Title = "导出原谱（不应用演奏适配参数）", FileName = string.Join("_", _song.Title.Split(Path.GetInvalidFileNameChars())), Filter = "琴伴 JSON|*.json|MIDI 文件|*.mid", DefaultExt = ".json", OverwritePrompt = true };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            if (dialog.FilterIndex == 1) File.WriteAllText(dialog.FileName, SongParser.ToJson(_song, false));
            else
            {
                // MIDI writer does not overwrite. Create alongside then replace only the explicitly selected export target.
                string temporary = dialog.FileName + "." + Guid.NewGuid().ToString("N") + ".mid";
                SongParser.WriteMidi(_song, temporary); File.Move(temporary, dialog.FileName, true);
            }
            Status("已导出原始标准化谱子；移调、倍速、和弦裁剪不写回原谱。");
        }
        catch (Exception ex) { ReportError(ex, "导出失败"); }
    }
    private void NewScore_Click(object sender, RoutedEventArgs e)
    {
        EditorBox.Text = "TITLE=我的第一首\nAUTHOR=我\nARTISTS=\nLANGUAGES=und\nALBUM=\nEDITION=\nBPM=100\nFORMAT=numbered\n\n1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2\n(135):2 0 1':2\n";
        EditorResult.Text = "修改后校验；另存会创建新谱。";
    }
    private void LoadEditor_Click(object sender, RoutedEventArgs e)
    {
        if (_song == null) return; EditorBox.Text = SongParser.ToJson(_song); EditorResult.Text = "已载入当前谱子的 JSON 副本。";
    }
    private SongDocument ParseEditor()
    {
        string text = EditorBox.Text.Trim();
        var song = text.StartsWith('{') || text.StartsWith('[') ? SongParser.ParseJson(text) : SongParser.ParseText(text);
        song.Category = "我的谱子"; song.Source = "琴伴谱子工坊 · 独立新副本"; return song;
    }
    private async void EditorPreview_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var song = ParseEditor(); EmergencyStop("已校验工坊谱子"); _song = song; _draft = true; _position = 0;
            _loadingOptions = true; TracksPanel.Children.Clear();
            foreach (var track in song.Tracks) { var c = new System.Windows.Controls.CheckBox { Content = $"{track.Name} · {track.NoteCount} 音", Tag = track.Id, IsChecked = true }; c.Checked += Option_Checked; c.Unchecked += Option_Checked; TracksPanel.Children.Add(c); }
            _loadingOptions = false; RebuildPlan(false); int epoch = _prepareEpoch; await WaitForPreparationAsync();
            if (epoch != _prepareEpoch || !_draft || !ReferenceEquals(_song, song) || _closing) return;
            NowTitle.Text = song.Title; FooterTitle.Text = song.Title;
            EditorResult.Text = $"校验成功 · {song.Notes.Count} 音 · {FormatTime(song.DurationMs)}";
            await StartPreviewAsync();
        }
        catch (Exception ex) { _loadingOptions = false; EditorResult.Text = "校验失败：" + ex.Message; ReportError(ex, "谱子校验失败"); }
    }
    private void EditorSave_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var song = ParseEditor(); var entry = _store.AddSong(song); SetPage("library"); SearchBox.Clear(); FilterCombo.SelectedIndex = 0; RefreshLibrary(); SelectEntry(entry); Status("已另存为新谱子，未覆盖原文件。");
        }
        catch (Exception ex) { EditorResult.Text = "保存失败：" + ex.Message; ReportError(ex, "工坊保存失败"); }
    }
    private void OpenData_Click(object sender, RoutedEventArgs e) => Process.Start(new ProcessStartInfo(_store.DataDirectory) { UseShellExecute = true });
}
