using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private const int LibraryPageSize = 50;
    // 中文大众主力 是默认入口；“中文流行候选”保留完整中文/粤语候选，“全部”仍保留给需要扩大浏览范围的用户。
    private const int ChinesePopFilterIndex = 5;
    private const int ChinesePopularFilterIndex = 6;
    private const int UnknownLanguageFilterIndex = 7;
    private const int ChinesePrioritySortIndex = 3;
    private int _libraryOffset, _libraryEpoch;
    private readonly DispatcherTimer _searchDebounce = new() { Interval = TimeSpan.FromMilliseconds(150) };
    private CancellationTokenSource? _libraryCancel;
    private Task _libraryTask = Task.CompletedTask;
    private bool _playlistLoading, _playlistRename;
    private LibraryPage? _libraryPage;
    private sealed record PlaylistChoice(string? Id, string Name, int Count)
    {
        public string Display => Id == null ? Name : $"{Name} ({Count})";
        public override string ToString() => Display;
    }
    private PlaylistChoice? SelectedPlaylist => PlaylistCombo.SelectedItem as PlaylistChoice;
    private void InitializeLibraryControls()
    {
        QualityCombo.SelectedIndex = 0;
        _searchDebounce.Tick += (_, _) => { _searchDebounce.Stop(); _libraryOffset = 0; RefreshLibrary(); };
        RefreshPlaylistChoices();
    }
    private void RefreshPlaylistChoices(string? selected = null)
    {
        selected ??= SelectedPlaylist?.Id;
        var items = new List<PlaylistChoice> { new(null, "全部谱目", 0) };
        items.AddRange(_store.Playlists().Select(p => new PlaylistChoice(p.Id, p.Name, p.Count)));
        _playlistLoading = true; PlaylistCombo.ItemsSource = items;
        PlaylistCombo.SelectedItem = items.FirstOrDefault(p => p.Id == selected) ?? items[0]; _playlistLoading = false;
    }
    private LibrarySort SelectedLibrarySort() => SortCombo.SelectedIndex switch
    {
        0 => LibrarySort.Added,
        1 => LibrarySort.Title,
        2 => LibrarySort.Duration,
        3 => LibrarySort.ChinesePopular,
        _ => LibrarySort.Added
    };
    private LibraryQuery CurrentLibraryQuery()
    {
        string? playlistId = SelectedPlaylist?.Id;
        LibrarySort sort = FilterCombo.SelectedIndex == 3 ? LibrarySort.Recent
            : playlistId != null || _page == "queue" ? LibrarySort.Added : SelectedLibrarySort();
        return new(SearchBox.Text.Trim(), (LibraryFilter)Math.Max(0, FilterCombo.SelectedIndex), sort,
            _page == "favorites", _page == "queue", playlistId,
            (LibraryQuality)Math.Max(0, QualityCombo.SelectedIndex), _libraryOffset, LibraryPageSize);
    }
    private static string ScopeHint(LibraryQuery query, LibraryPage page, LibraryLanguageSummary summary)
    {
        return query.Filter switch
        {
            LibraryFilter.ChinesePop => $"中文流行候选 · {summary.ChinesePop:N0} 条（中文大众主力精选 {summary.ChinesePopular:N0} 条）",
            LibraryFilter.ChinesePopular => $"大众中文精选 · {summary.ChinesePopular:N0} 条（编辑优先，不是平台实时榜单）",
            LibraryFilter.UnknownLanguage => $"语种待核验 · {summary.UnknownLanguage:N0} 条（不把未标注条目当作英文）",
            LibraryFilter.All => $"全部曲库 · {summary.Total:N0} 条（中文流行 {summary.ChinesePop:N0}，大众主力 {summary.ChinesePopular:N0}，明确英文 {summary.ExplicitEnglish:N0}，语种待核验 {summary.UnknownLanguage:N0}）",
            _ => $"当前筛选 {page.Total:N0} 条 · 中文大众主力 {summary.ChinesePopular:N0} 条"
        };
    }

    private static string ScopeTooltip(LibraryLanguageSummary summary) =>
        $"中文流行 {summary.ChinesePop:N0} 条；大众中文精选 {summary.ChinesePopular:N0} 条；明确标记英文 {summary.ExplicitEnglish:N0} 条；语种未标注 {summary.UnknownLanguage:N0} 条。未标注条目不会自动归类为英文或中文。";
    private void RefreshLibrary()
    {
        if (!_ready || _closing) return;
        _searchDebounce.Stop(); _libraryTask = RefreshLibraryAsync();
    }
    private async Task RefreshLibraryAsync()
    {
        int epoch = ++_libraryEpoch;
        _libraryCancel?.Cancel(); var cancel = new CancellationTokenSource(); _libraryCancel = cancel;
        var query = CurrentLibraryQuery(); 
        LibraryLoadingText.Visibility = Visibility.Visible;
        try
        {
            var result = await Task.Run(() =>
            {
                var page = _store.Query(query, cancel.Token);
                var summary = _store.LanguageSummary();
                return (page, summary);
            }, cancel.Token);
            var page = result.page;
            var summary = result.summary;
            if (page.Total > 0 && _libraryOffset >= page.Total)
            {
                _libraryOffset = (page.Total - 1) / LibraryPageSize * LibraryPageSize; RefreshLibrary(); return;
            }
            _libraryPage = page;
            _loadingOptions = true;
            try { SongList.ItemsSource = page.Items; SongList.SelectedItem = page.Items.FirstOrDefault(e => e.Id == _selected?.Id); }
            finally { _loadingOptions = false; }
            LibraryCount.Text = $"{page.Total:N0} / {page.LibraryTotal:N0} 条";
            LibraryCount.ToolTip = ScopeTooltip(summary);
            LibraryScopeHint.Text = ScopeHint(query, page, summary);
            LibraryScopeHint.ToolTip = ScopeTooltip(summary);
            PageCountText.Text = $"{(page.Total == 0 ? 0 : page.Offset / LibraryPageSize + 1)} / {Math.Max(1, (page.Total + LibraryPageSize - 1) / LibraryPageSize)} 页";
            PreviousPageButton.IsEnabled = _libraryOffset > 0; NextPageButton.IsEnabled = _libraryOffset + page.Items.Count < page.Total;
            EmptyState.Visibility = page.Total == 0 ? Visibility.Visible : Visibility.Collapsed;
            EmptyState.Text = query.Filter == LibraryFilter.Samples && page.Total == 0 ? "尚未取得合格的公开谱源样本。\n不会用生成曲或目录占位凑数。" : query.Filter is LibraryFilter.ChinesePop or LibraryFilter.ChinesePopular && page.Total == 0 ? "当前没有匹配的中文流行谱。\n可切换“全部语言”查看其它来源，或导入自己的谱子。" : "没有找到曲谱\n清空搜索或筛选，或导入自己的谱子。";
            LibraryLoadingText.Visibility = Visibility.Collapsed;
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            if (!_closing && epoch == _libraryEpoch) { LibraryLoadingText.Visibility = Visibility.Collapsed; ReportError(ex, "曲库查询失败，保留上一次结果"); }
        }
        finally { if (ReferenceEquals(_libraryCancel, cancel)) _libraryCancel = null; cancel.Dispose(); }
    }
    private void CancelLibraryQuery() { _searchDebounce.Stop(); _libraryCancel?.Cancel(); }
    private void Search_Changed(object sender, TextChangedEventArgs e)
    {
        if (!_ready || _closing) return;
        ++_libraryEpoch; _libraryCancel?.Cancel(); _searchDebounce.Stop(); _searchDebounce.Start();
    }
    private void Filter_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_ready || _playlistLoading) return; _libraryOffset = 0; RefreshLibrary();
    }
    private void PreviousPage_Click(object sender, RoutedEventArgs e) { _libraryOffset = Math.Max(0, _libraryOffset - LibraryPageSize); RefreshLibrary(); }
    private void NextPage_Click(object sender, RoutedEventArgs e)
    {
        if (_libraryPage != null && _libraryOffset + LibraryPageSize < _libraryPage.Total) { _libraryOffset += LibraryPageSize; RefreshLibrary(); }
    }
    private void LibraryTools_Click(object sender, RoutedEventArgs e)
    {
        LibraryToolsPanel.Visibility = LibraryToolsPanel.Visibility == Visibility.Visible ? Visibility.Collapsed : Visibility.Visible;
        LibraryToolsButton.Content = LibraryToolsPanel.Visibility == Visibility.Visible ? "收起管理" : "筛选 / 歌单";
    }
    private void PlaylistNew_Click(object sender, RoutedEventArgs e)
    {
        _playlistRename = false; PlaylistNameBox.Text = ""; PlaylistPopupTitle.Text = "新建歌单"; PlaylistNamePopup.IsOpen = true;
        Dispatcher.BeginInvoke(() => PlaylistNameBox.Focus());
    }
    private void PlaylistRename_Click(object sender, RoutedEventArgs e)
    {
        if (SelectedPlaylist?.Id == null) { Status("先在歌单列表选择一个歌单。"); return; }
        _playlistRename = true; PlaylistNameBox.Text = SelectedPlaylist.Name; PlaylistPopupTitle.Text = "重命名歌单"; PlaylistNamePopup.IsOpen = true;
        Dispatcher.BeginInvoke(() => { PlaylistNameBox.Focus(); PlaylistNameBox.SelectAll(); });
    }
    private void PlaylistConfirm_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            string? id = SelectedPlaylist?.Id;
            if (_playlistRename) { if (id == null) throw new FormatException("歌单已改变，请重新选择。"); _store.RenamePlaylist(id, PlaylistNameBox.Text); }
            else id = _store.CreatePlaylist(PlaylistNameBox.Text).Id;
            RefreshPlaylistChoices(id); PlaylistNamePopup.IsOpen = false; _libraryOffset = 0; RefreshLibrary(); Status("歌单已保存，只保存在本机。");
        }
        catch (Exception ex) { ReportError(ex, "歌单未保存"); }
    }
    private void PlaylistCancel_Click(object sender, RoutedEventArgs e) { PlaylistNamePopup.IsOpen = false; LibraryToolsButton.Focus(); }
    private void PlaylistName_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) { PlaylistConfirm_Click(sender, new()); e.Handled = true; }
        else if (e.Key == Key.Escape) { PlaylistCancel_Click(sender, new()); e.Handled = true; }
    }
    private List<LibraryEntry> SelectedLibraryEntries()
    {
        var entries = SongList.SelectedItems.OfType<LibraryEntry>().ToList();
        if (entries.Count == 0 && _selected != null) entries.Add(_selected); return entries;
    }
    private void PlaylistAdd_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            if (SelectedPlaylist?.Id is not { } id) throw new FormatException("先创建或选择一个歌单。");
            var entries = SelectedLibraryEntries(); if (entries.Count == 0) throw new FormatException("先选择曲谱。");
            _store.AddToPlaylist(id, entries); RefreshPlaylistChoices(id); RefreshLibrary(); Status($"已把 {entries.Count} 份所选曲谱加入歌单；重复项不增加。");
        }
        catch (Exception ex) { ReportError(ex, "加入歌单失败"); }
    }
    private void PlaylistRemove_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            if (SelectedPlaylist?.Id is not { } id) throw new FormatException("先选择一个歌单。");
            var entries = SelectedLibraryEntries(); _store.RemoveFromPlaylist(id, entries); RefreshPlaylistChoices(id); RefreshLibrary(); Status("已移出歌单，谱文件与收藏未删除。");
        }
        catch (Exception ex) { ReportError(ex, "移出歌单失败"); }
    }
    private void PlaylistDelete_Click(object sender, RoutedEventArgs e)
    {
        if (SelectedPlaylist?.Id is not { } id) { Status("先选择一个歌单。"); return; }
        if (!_uiTest && MessageBox.Show(this, "只删除歌单及其排列，不删除曲谱、原文件或收藏。继续吗？", "删除歌单", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        try { _store.DeletePlaylist(id); RefreshPlaylistChoices(); PlaylistCombo.SelectedIndex = 0; _libraryOffset = 0; RefreshLibrary(); Status("歌单已删除；谱文件未删除。"); }
        catch (Exception ex) { ReportError(ex, "删除歌单失败"); }
    }
    private void BulkFavorite_Click(object sender, RoutedEventArgs e)
    {
        try { var entries = SelectedLibraryEntries(); foreach (var entry in entries) entry.Favorite = true; _store.SaveMany(entries); if (_selected != null) FavoriteButton.Content = _selected.FavoriteText; RefreshLibrary(); Status($"已收藏 {entries.Count} 份所选曲谱。"); }
        catch (Exception ex) { ReportError(ex, "批量收藏未保存"); }
    }
    private static string MetadataValue(string value) => string.IsNullOrWhiteSpace(value) ? "未知" : value.Trim();
    private static string MetadataDetails(ScoreProvenance provenance, string author, string category) =>
        $"歌手：{SongMetadata.ArtistText(provenance)}\n语种：{SongMetadata.LanguageText(provenance)}"
        + $"\n版本：{MetadataValue(provenance.VersionLabel)}\n作者 / 编谱者：{MetadataValue(author)}"
        + $"\n专辑：{MetadataValue(provenance.Album)}\n分类：{MetadataValue(category)}";
    private void ShowSongMetadata(ScoreProvenance provenance, string author, string category)
    {
        NowAuthor.Text = $"歌手：{SongMetadata.ArtistText(provenance)} · 语种：{SongMetadata.LanguageText(provenance)} · 版本：{MetadataValue(provenance.VersionLabel)}";
        NowAuthor.ToolTip = MetadataDetails(provenance, author, category);
    }
    private string ProvenanceSummary()
    {
        var p = _song?.Provenance ?? _selected?.Provenance;
        if (p == null) return "未认证的个人编辑副本。";
        string quality = _selected == null || _draft ? "未认证的个人编辑副本。" : _selected.QualityText;
        return quality + "\n" + (p.License == "unverified" ? "许可：待核验" : "许可声明：" + MetadataValue(p.License))
            + (p.SourceUrl.Length > 0 ? "\n来源：" + p.SourceUrl : "")
            + (p.LicenseUrl.Length > 0 ? "\n许可说明：" + p.LicenseUrl : "")
            + $"\n提供方：{MetadataValue(p.Provider)}\n时序校验：{MetadataValue(p.TimingStatus)}"
            + $"\n音乐审校：{MetadataValue(p.MusicReview)}\n游戏实测：{MetadataValue(p.GameReview)}"
            + (p.Synthetic ? "\n数据性质：合成测试夹具（不是真实收录歌曲）" : "")
            + "\n" + MetadataDetails(p, _song?.Author ?? _selected?.Author ?? "", _song?.Category ?? _selected?.Category ?? "")
            + "\n原谱、时序校验、人工审校与游戏实测分别记录，不互相代替。";
    }
    private async Task WaitForLibraryAsync()
    {
        var timeout = System.Diagnostics.Stopwatch.StartNew();
        while (timeout.Elapsed < TimeSpan.FromSeconds(15))
        {
            if (_searchDebounce.IsEnabled) { await Task.Delay(20); continue; }
            var task = _libraryTask; await task;
            if (!ReferenceEquals(task, _libraryTask) || _searchDebounce.IsEnabled) continue;

            // The query continuation assigns ItemsSource on the dispatcher, but WPF may
            // publish the new Items collection at DataBind/Loaded priority. Callers in
            // validation and event handlers must not observe the previous page during
            // that small window (it becomes visible with larger catalogues).
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.DataBind);
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Loaded);
            UpdateLayout();
            if (ReferenceEquals(task, _libraryTask) && !_searchDebounce.IsEnabled
                && (_libraryPage == null || SongList.Items.Count == _libraryPage.Items.Count)) return;
        }
        throw new TimeoutException("曲库查询未在 15 秒内完成。");
    }
}
