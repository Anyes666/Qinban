using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private async Task RunScaleValidationAsync()
    {
        string output = Path.GetDirectoryName(_store.DataDirectory)!;
        var results = new List<object>(); int failures = 0;
        void Check(bool ok, string why) { if (!ok) throw new Exception(why); }
        async Task Test(string name, Func<Task> action)
        {
            var watch = Stopwatch.StartNew();
            try { await action(); results.Add(new { name, status = "PASS", milliseconds = watch.Elapsed.TotalMilliseconds }); }
            catch (Exception ex) { failures++; results.Add(new { name, status = "FAIL", error = ex.ToString(), milliseconds = watch.Elapsed.TotalMilliseconds }); }
        }
        int count = _store.Count, readsAtOpen = _store.SongReads;
        await Test("Large catalogue opens one page and only selected score", () =>
        {
            Check(count is 20000 or 50000 && SongList.Items.Count == 50 && readsAtOpen == 1, "eager loading / count");
            Check(_selected!.Provenance.Synthetic && _song!.Provenance.Synthetic, "not a declared synthetic fixture");
            Check(VirtualizingPanel.GetIsVirtualizing(SongList) && VirtualizingPanel.GetVirtualizationMode(SongList) == VirtualizationMode.Recycling, "no recycling virtualization");
            return Task.CompletedTask;
        });
        await Test("Debounced Chinese, pinyin, artist, language, album, version and empty search render correctly", async () =>
        {
            foreach (string term in new[] { "星", "星光", "xingguang", "zwsscsxg", "fixture000123" })
            {
                SearchBox.Text = term; await WaitForLibraryAsync(); Check(SongList.Items.Count == 1 && _libraryPage!.Total == 1, "missing: " + term);
            }
            SearchBox.Text = "合成 测试作者甲"; await WaitForLibraryAsync(); Check(_libraryPage!.Total == count / 2 && SongList.Items.Count == 50, "combination / page size");
            foreach (string term in new[] { "合作歌手乙 cmn", "国语 英语 测试专辑 录音室版", "粤语 合作歌手丙 现场版" })
            {
                SearchBox.Text = term; await WaitForLibraryAsync();
                Check(_libraryPage!.Total == count / 2 && SongList.Items.Count == 50, "identity combination / page size: " + term);
            }
            SearchBox.Text = "not-present-fixture"; await WaitForLibraryAsync(); Check(SongList.Items.Count == 0 && EmptyState.Visibility == Visibility.Visible, "empty search");
            Check(_store.SongReads == readsAtOpen, "search read scores");
        });
        await Test("Superseded query cannot replace final search results", async () =>
        {
            SearchBox.Text = "合成"; RefreshLibrary(); SearchBox.Text = "星光"; await WaitForLibraryAsync();
            Check(SongList.Items.Count == 1 && ((LibraryEntry)SongList.Items[0]).Id == "synthetic:000123", "stale result applied");
            SearchBox.Clear(); await WaitForLibraryAsync();
        });
        await Test("Paging and next/previous song cross page boundaries without whole-library materialization", async () =>
        {
            SongList.SelectedIndex = 49; await WaitForPreparationAsync(); string previous = _selected!.Id;
            Next_Click(this, new()); await _navigationTask;
            Check(_libraryOffset == 50 && _selected!.Id == "synthetic:000050" && SongList.SelectedItem == _selected, "next stayed on old page");
            Previous_Click(this, new()); await _navigationTask;
            Check(_libraryOffset == 0 && _selected!.Id == previous, "previous failed cross-page");
            NextPage_Click(this, new()); await WaitForLibraryAsync(); Check(SongList.Items.Count == 50 && ((LibraryEntry)SongList.Items[0]).Id == "synthetic:000050", "page 2");
            PreviousPage_Click(this, new()); await WaitForLibraryAsync();
        });
        await Test("Selected fixture is explicitly denied real keyboard output", async () =>
        {
            bool rejected = false; try { ScorePlaybackPolicy.EnsureRealInputAllowed(_song!, _selected); } catch (InvalidOperationException) { rejected = true; }
            Check(rejected && !GameButton.IsEnabled, "synthetic input not guarded / UI enabled"); Game_Click(this, new()); await ShortcutStartAsync();
            Check(_nativeAttempts == 0 && _sink == null, "native input attempted");
        });
        await Test("Large-library bulk favorite and local playlist controls", async () =>
        {
            SongList.SelectedItems.Clear(); SongList.SelectedItems.Add(SongList.Items[0]); SongList.SelectedItems.Add(SongList.Items[1]);
            BulkFavorite_Click(this, new()); await WaitForLibraryAsync(); SetPage("favorites"); await WaitForLibraryAsync(); Check(SongList.Items.Count == 2, "bulk favorite filter");
            SetPage("library"); await WaitForLibraryAsync();
            PlaylistNew_Click(this, new()); PlaylistNameBox.Text = "压力数据歌单（不是歌曲）"; PlaylistConfirm_Click(this, new()); await WaitForLibraryAsync();
            PlaylistAdd_Click(this, new()); await WaitForLibraryAsync(); Check(SongList.Items.Count == 1, "playlist local selection");
            PlaylistDelete_Click(this, new()); await WaitForLibraryAsync(); Check(_store.Count == count && SongList.Items.Count == 50, "playlist removed scores");
        });
        await Test("Full and minimum viewport render paginated catalogue", async () =>
        {
            SelectEntry(_store.Query(new()).Items[0]); await WaitForPreparationAsync();
            foreach (var size in new[] { (1460d, 940d), (1120d, 780d) })
            {
                Width = size.Item1; Height = size.Item2; UpdateLayout(); await Task.Delay(100);
                Capture(Path.Combine(output, "scale-" + (int)size.Item1 + ".png")); CheckFooterBounds();
                Check(SongList.ActualHeight > 100 && PageCountText.IsVisible && NextPageButton.IsVisible, "paging controls hidden");
                var point = NextPageButton.TransformToAncestor(LibraryPanel).Transform(new Point(0, NextPageButton.ActualHeight));
                Check(point.Y <= LibraryPanel.ActualHeight + 1, "paging clipped");
                int realized = Enumerable.Range(0,SongList.Items.Count).Count(i => SongList.ItemContainerGenerator.ContainerFromIndex(i) != null);
                Check(realized < SongList.Items.Count, "all page containers realized despite virtualization");
            }
        });
        File.WriteAllText(Path.Combine(output,"scale-ui-report.json"),JsonSerializer.Serialize(new { recordedAtUtc = DateTimeOffset.UtcNow, count, actualSongsAdded = 0,
            dataset = "synthetic metadata only; not music quality evidence", firstPageItems = 50, readsAtOpen, nativeSendAttempts = _nativeAttempts,
            failures, unhandled = _validationUnhandled, processMemoryMiB = Process.GetCurrentProcess().WorkingSet64 / 1048576d, results },JsonDefaults.Options));
        Application.Current.Shutdown(failures == 0 && _nativeAttempts == 0 && _validationUnhandled.Count == 0 ? 0 : 1);
    }
}
