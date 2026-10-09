using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    // The main validation driver calls this after its original cases. Nothing here runs in normal use.
    private async Task ValidateMetadataAsync(string output, Func<string, Func<Task>, Task> test, Action<bool, string> check)
    {
        string[] args = Environment.GetCommandLineArgs(); int dataAt = Array.IndexOf(args, "--data-dir");
        string Canonical(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (!_uiTest || dataAt < 0 || dataAt + 1 >= args.Length
            || !Canonical(args[dataAt + 1]).Equals(Canonical(_store.DataDirectory), StringComparison.OrdinalIgnoreCase)
            || Canonical(_store.DataDirectory).Equals(Canonical(Path.Combine(AppContext.BaseDirectory, "UserData")), StringComparison.OrdinalIgnoreCase)
            || !Canonical(output).Equals(Canonical(Path.GetDirectoryName(_store.DataDirectory)!), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("元数据自测仅允许 --ui-test、显式独立 --data-dir 及其隔离输出目录；不写既有默认 UserData。");
        await WaitForLibraryAsync(); await WaitForPreparationAsync();
        var savedEntry = _selected;
        string savedPage = _page, savedSearch = SearchBox.Text, savedEditor = EditorBox.Text, savedEditorResult = EditorResult.Text;
        int savedFilter = FilterCombo.SelectedIndex, savedSort = SortCombo.SelectedIndex, savedQuality = QualityCombo.SelectedIndex, savedOffset = _libraryOffset;
        string? savedPlaylist = SelectedPlaylist?.Id;
        string[] savedSelection = SongList.SelectedItems.OfType<LibraryEntry>().Select(e => e.Id).ToArray();
        double savedWidth = Width, savedHeight = Height, savedScroll = WorkbenchScroll.VerticalOffset;
        bool savedExpanded = AdaptationExpander.IsExpanded;
        var savedTools = LibraryToolsPanel.Visibility; object savedToolsLabel = LibraryToolsButton.Content;
        var savedOverlay = ParameterOverlay.Visibility; object savedParametersLabel = ParametersToggle.Content;
        int beforeCount = _store.Count;
        var fixture = new SongDocument
        {
            Title = "元数据自制合成夹具（不是收录歌曲）", Author = "夹具编谱者（不是歌手）", Category = "隔离元数据验证",
            Source = "隔离 UI 元数据夹具 · 不是真实谱源", Description = "仅检验界面、检索和输入保护，不证明音乐正文、许可或游戏内演奏。",
            Bpm = 100, Notes = [new(60, 0, 250), new(64, 500, 250)], LengthMs = 1000,
            Provenance = new()
            {
                Synthetic = true, Artists = ["验证歌手甲", "验证歌手乙"], Artist = "旧歌手回退（新列表优先）",
                LanguageTags = ["cmn", "en"], Album = "合成元数据专辑", VersionLabel = "联合演唱测试版",
                Provider = "local-synthetic-ui", SourceUrl = "https://example.invalid/qinban/metadata-fixture",
                License = "unverified", TimingStatus = "unverified", MusicReview = "not-reviewed", GameReview = "not-tested"
            }
        };
        LibraryEntry? added = null;
        LibraryEntry FixtureEntry() => added ?? throw new InvalidOperationException("前置 synthetic 元数据夹具未成功创建。");
        try
        {
            await test("Workshop metadata template preserves author, empty artists and explicitly unknown language", () =>
            {
                NewScore_Click(this, new());
                foreach (string header in new[] { "AUTHOR=我", "ARTISTS=", "LANGUAGES=und", "ALBUM=", "EDITION=" })
                    check(EditorBox.Text.Split('\n').Any(line => line.TrimEnd('\r') == header), "missing exact template header: " + header);
                var song = ParseEditor(); song.Provenance.Synthetic = true;
                check(song.Author == "我" && song.Provenance.Artists.Count == 0 && song.Provenance.Artist.Length == 0, "author was used as an artist");
                check(song.Provenance.LanguageTags.SequenceEqual(new[] { "und" }) && SongMetadata.LanguageText(song.Provenance) == "语种未知", "unknown language inferred");
                check(song.Provenance.Album.Length == 0 && song.Provenance.VersionLabel.Length == 0, "blank album/version filled");
                EditorBox.Text = EditorBox.Text.Replace("ARTISTS=\n", "ARTISTS=验证歌手甲|验证歌手乙\n")
                    .Replace("LANGUAGES=und", "LANGUAGES=cmn|en").Replace("ALBUM=\n", "ALBUM=合成元数据专辑\n")
                    .Replace("EDITION=\n", "EDITION=联合演唱测试版\n");
                var multiple = ParseEditor(); multiple.Provenance.Synthetic = true;
                check(multiple.Author == "我" && multiple.Provenance.Artists.SequenceEqual(fixture.Provenance.Artists)
                    && multiple.Provenance.LanguageTags.SequenceEqual(fixture.Provenance.LanguageTags)
                    && multiple.Provenance.Album == fixture.Provenance.Album && multiple.Provenance.VersionLabel == fixture.Provenance.VersionLabel, "multi-value text metadata lost");
                check(_store.Count == beforeCount, "template validation saved or overwrote a score");
                return Task.CompletedTask;
            });
            await test("Actual list selection immediately shows entry metadata while asynchronous preparation is pending", async () =>
            {
                added = _store.AddSong(fixture);
                check(added.Provenance.Synthetic && !added.Provenance.IsFormalSong && _store.Count == beforeCount + 1, "fixture was counted as a formal song or added more than once");
                SetPage("library"); FilterCombo.SelectedIndex = 0; SortCombo.SelectedIndex = 0; QualityCombo.SelectedIndex = 0;
                PlaylistCombo.SelectedIndex = 0; SearchBox.Text = fixture.Title; _libraryOffset = 0; RefreshLibrary(); await WaitForLibraryAsync();
                var entry = SongList.Items.OfType<LibraryEntry>().Single(e => e.Id == added.Id);
                // Hold the preparer's single-flight slot on a worker, not the UI dispatcher. No timing sleep/race.
                var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                var blocker = _scorePreparer.PrepareAsync(() =>
                {
                    entered.TrySetResult(); release.Task.WaitAsync(TimeSpan.FromSeconds(30)).GetAwaiter().GetResult(); return fixture.Copy();
                }, entry.Options.Copy());
                try
                {
                    await entered.Task.WaitAsync(TimeSpan.FromSeconds(30));
                    SongList.SelectedItems.Clear(); SongList.SelectedItem = entry;
                    check(_selected?.Id == entry.Id && _preparing && _song == null, "real SelectionChanged did not enter pending state");
                    check(NowAuthor.Text.Contains("验证歌手甲 / 验证歌手乙") && NowAuthor.Text.Contains("国语 / 英语")
                        && NowAuthor.Text.Contains("联合演唱测试版") && !NowAuthor.Text.Contains(fixture.Author) && !NowAuthor.Text.Contains(fixture.Provenance.Artist), "pending author/legacy field substituted for artists");
                    check(NowAuthor.ToolTip is string tooltip && tooltip.Contains("作者 / 编谱者：" + fixture.Author)
                        && tooltip.Contains("专辑：" + fixture.Provenance.Album) && SourceText.Text.Contains("许可：待核验")
                        && SourceText.Text.Contains("联合演唱测试版"), "pending metadata/permission tooltip is stale");
                    check(_plan == null && !PreviewButton.IsEnabled && _nativeAttempts == 0 && _sink == null, "pending score became playable or touched native input");
                }
                finally { release.TrySetResult(); await blocker.WaitAsync(TimeSpan.FromSeconds(30)); }
                await WaitForPreparationAsync();
                check(_song != null && _song.Provenance.Synthetic && !_preparing && _plan?.Notes.Count > 0, "fixture did not prepare");
                check(NowAuthor.Text.Contains("验证歌手乙") && NowAuthor.Text.Contains("国语 / 英语") && NowAuthor.Text.Contains("版本：联合演唱测试版"), "prepared summary lost metadata");
                foreach (string value in new[] { "歌手：验证歌手甲 / 验证歌手乙", "语种：国语 / 英语", "版本：联合演唱测试版",
                    "作者 / 编谱者：" + fixture.Author, "专辑：合成元数据专辑", "分类：隔离元数据验证", "许可：待核验",
                    "时序校验：unverified", "音乐审校：not-reviewed", "游戏实测：not-tested", fixture.Provenance.SourceUrl })
                    check(SourceText.Text.Contains(value), "source panel missing: " + value);
                check(SourceText.Text.Contains("合成测试夹具") && !GameButton.IsEnabled && !SourceText.Text.Contains("CC0"), "synthetic/permission boundary replaced");
            });
            await test("Rendered library metadata row and tooltip retain metadata, arranger and category", async () =>
            {
                SearchBox.Text = fixture.Title; await WaitForLibraryAsync();
                await WaitForPreparationAsync(); var entry = FixtureEntry();
                var visible = SongList.Items.OfType<LibraryEntry>().Single(e => e.Id == entry.Id);
                SongList.ScrollIntoView(visible); UpdateLayout();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Loaded); UpdateLayout();
                var container = SongList.ItemContainerGenerator.ContainerFromItem(visible) as ListBoxItem;
                check(container != null, "selected fixture container was not realized");
                var metadata = MetadataVisuals(container!).OfType<TextBlock>().Single(t => t.Text == visible.MetadataText);
                check(metadata.Text.Contains(visible.ArtistText) && metadata.Text.Contains(visible.LanguageText)
                    && metadata.Text.Contains(fixture.Provenance.VersionLabel) && metadata.TextTrimming == TextTrimming.CharacterEllipsis, "metadata row binding/ellipsis");
                check(metadata.ToolTip is string tooltip && tooltip.Contains(visible.MetadataText)
                    && tooltip.Contains("作者 / 编谱者：" + fixture.Author) && tooltip.Contains("分类：" + fixture.Category), "metadata tooltip lost classification/arranger");
            });
            await test("Artist, language, album, edition and combined searches pass through the actual async library pipeline", async () =>
            {
                foreach (string query in new[] { "验证歌手甲", "验证歌手乙", "英语 合成元数据专辑", "合成元数据专辑", "联合演唱测试版",
                    "验证歌手甲 英语 合成元数据专辑 联合演唱测试版", "元数据 验证歌手乙 国语" })
                {
                    SearchBox.Text = query; await WaitForLibraryAsync();
                    check(SongList.Items.OfType<LibraryEntry>().Any(e => e.Id == FixtureEntry().Id), "search lost the fixture: " + query);
                }
                SearchBox.Clear(); await WaitForLibraryAsync();
                check(_libraryPage?.Total == beforeCount + 1 && _store.Count == beforeCount + 1, "clearing search modified the catalog");
                SearchBox.Text = fixture.Title; await WaitForLibraryAsync();
                check((SongList.SelectedItem as LibraryEntry)?.Id == FixtureEntry().Id && _selected?.Id == FixtureEntry().Id, "fixture selection was not recoverable after clearing search");
            });
            await test("Prepared-song metadata takes precedence, supports legacy artist fallback and never guesses missing language", async () =>
            {
                var legacy = fixture.Copy(); legacy.Provenance.Artists = []; legacy.Provenance.Artist = "旧字段歌手";
                legacy.Provenance.LanguageTags = []; legacy.Provenance.Album = ""; legacy.Provenance.VersionLabel = "";
                QueuePreparation(() => legacy, ReadOptions(), false, false); await WaitForPreparationAsync();
                check(ReferenceEquals(_song, legacy) && NowAuthor.Text.Contains("歌手：旧字段歌手") && NowAuthor.Text.Contains("语种：语种未知")
                    && NowAuthor.Text.Contains("版本：未知") && !NowAuthor.Text.Contains(fixture.Author) && !NowAuthor.Text.Contains("验证歌手甲"), "prepared song/legacy fallback was replaced by cached entry or author");
                check(NowAuthor.ToolTip is string tooltip && tooltip.Contains("作者 / 编谱者：" + fixture.Author)
                    && tooltip.Contains("专辑：未知") && SourceText.Text.Contains("歌手：旧字段歌手") && SourceText.Text.Contains("许可：待核验"), "legacy metadata details lost");
                var unknown = legacy.Copy(); unknown.Provenance.Artist = ""; unknown.Provenance.LanguageTags = ["und"];
                QueuePreparation(() => unknown, ReadOptions(), false, false); await WaitForPreparationAsync();
                check(NowAuthor.Text.Contains("歌手：歌手未标注") && NowAuthor.Text.Contains("语种：语种未知") && NowAuthor.Text.Contains("版本：未知")
                    && SourceText.Text.Contains("专辑：未知") && !GameButton.IsEnabled, "unknown metadata was inferred or synthetic guard changed");
                check(FixtureEntry().Provenance.Artists.SequenceEqual(fixture.Provenance.Artists)
                    && FixtureEntry().Provenance.LanguageTags.SequenceEqual(fixture.Provenance.LanguageTags), "display checks mutated stored provenance");
                SongList.SelectedItems.Clear(); SongList.SelectedItem = SongList.Items.OfType<LibraryEntry>().Single(e => e.Id == FixtureEntry().Id);
                await WaitForPreparationAsync();
            });
            await test("Metadata remains available in tooltips without clipping persistent controls at the minimum viewport", async () =>
            {
                SetPage("library"); await WaitForLibraryAsync(); await WaitForPreparationAsync();
                Width = MinWidth; Height = MinHeight; AdaptationExpander.IsExpanded = false; WorkbenchScroll.ScrollToTop(); UpdateLayout();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Loaded); UpdateLayout();
                check(NowAuthor.IsVisible && NowAuthor.ActualWidth > 0 && NowAuthor.ActualWidth < WorkbenchScroll.ActualWidth
                    && NowAuthor.TextTrimming == TextTrimming.CharacterEllipsis, "metadata text displaced the workbench");
                check(NowAuthor.ToolTip is string tooltip && tooltip.Contains("验证歌手乙") && tooltip.Contains("专辑：合成元数据专辑")
                    && tooltip.Contains("版本：联合演唱测试版"), "minimum-width metadata tooltip incomplete");
                CheckFooterBounds(); Capture(Path.Combine(output, "metadata-minimum-viewport.png"));
                check(_nativeAttempts == 0 && _sink == null && !_gameHotkeyEnabled, "metadata tests enabled native input");
            });
        }
        finally
        {
            // Keep the single explicitly synthetic score in this run's isolated data, not in Songs or old UserData.
            await test("Metadata validation restores the original UI query, page and song selection without native input", async () =>
            {
                EditorBox.Text = savedEditor; EditorResult.Text = savedEditorResult;
                Width = savedWidth; Height = savedHeight;
                FilterCombo.SelectedIndex = savedFilter; SortCombo.SelectedIndex = savedSort; QualityCombo.SelectedIndex = savedQuality;
                PlaylistCombo.SelectedItem = PlaylistCombo.Items.OfType<PlaylistChoice>().FirstOrDefault(p => p.Id == savedPlaylist) ?? PlaylistCombo.Items[0];
                SearchBox.Text = savedSearch; SetPage(savedPage); _libraryOffset = savedOffset; RefreshLibrary(); await WaitForLibraryAsync();
                _loadingOptions = true;
                try
                {
                    SongList.SelectedItems.Clear();
                    foreach (var entry in SongList.Items.OfType<LibraryEntry>().Where(e => savedSelection.Contains(e.Id))) SongList.SelectedItems.Add(entry);
                }
                finally { _loadingOptions = false; }
                if (savedEntry != null) { SelectEntry(savedEntry); await WaitForPreparationAsync(); }
                LibraryToolsPanel.Visibility = savedTools; LibraryToolsButton.Content = savedToolsLabel;
                ParameterOverlay.Visibility = savedOverlay; ParametersToggle.Content = savedParametersLabel;
                AdaptationExpander.IsExpanded = savedExpanded; UpdateLayout(); WorkbenchScroll.ScrollToVerticalOffset(savedScroll);
                check(_page == savedPage && SearchBox.Text == savedSearch && _libraryOffset == savedOffset
                    && FilterCombo.SelectedIndex == savedFilter && SortCombo.SelectedIndex == savedSort && QualityCombo.SelectedIndex == savedQuality
                    && SelectedPlaylist?.Id == savedPlaylist && _selected?.Id == savedEntry?.Id, "original UI state/selection not restored");
                check(savedEntry == null || _song?.Title == savedEntry.Title, "restored song did not finish preparation");
                check(_store.Count == beforeCount + (added == null ? 0 : 1) && _nativeAttempts == 0 && _sink == null && _validationUnhandled.Count == 0,
                    "metadata fixture count, native input or dispatcher guard changed");
            });
        }
    }
    private static IEnumerable<DependencyObject> MetadataVisuals(DependencyObject root)
    {
        yield return root;
        for (int i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
            foreach (var child in MetadataVisuals(VisualTreeHelper.GetChild(root, i))) yield return child;
    }
}
