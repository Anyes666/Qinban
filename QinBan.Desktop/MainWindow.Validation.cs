using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private readonly List<string> _validationUnhandled = [];
    public bool HandleValidationError(Exception exception)
    {
        if (!_uiTest) return false;
        _validationUnhandled.Add(exception.ToString()); EmergencyStop("自测捕获异常"); return true;
    }
    private static bool IsChinesePopEntry(LibraryEntry entry) => entry.Provenance.Tags.Any(tag => tag is "中文歌曲" or "中文流行" or "中文流行候选" or "粤语歌曲" or "粤语流行" or "粤语流行候选");

    private async Task RunUiValidationAsync()
    {
        if (_uiTest && Environment.GetCommandLineArgs().Contains("--smart-interlude-validation")) { await RunSmartInterludeValidationAsync(); return; }
        try { await Task.Delay(250); _timer.Stop(); await WaitForLibraryAsync(); await WaitForPreparationAsync(); }
        catch (Exception ex) when (_uiTest && Environment.GetCommandLineArgs().Contains("--audition-validation"))
        {
            await RunAuditionValidationAsync(ex); return;
        }
        if (_uiTest && Environment.GetCommandLineArgs().Contains("--scroll-validation")) { await RunScrollValidationAsync(); return; }
        if (_uiTest && Environment.GetCommandLineArgs().Contains("--audition-validation")) { await RunAuditionValidationAsync(); return; }
        if (Environment.GetCommandLineArgs().Contains("--preparation-validation")) { await RunPreparationValidationAsync(); return; }
        if (Environment.GetCommandLineArgs().Contains("--scale-validation")) { await RunScaleValidationAsync(); return; }
        string output = Path.GetDirectoryName(_store.DataDirectory)!; Directory.CreateDirectory(output);
        if (Environment.GetCommandLineArgs().Contains("--capture-only"))
        {
            if (!TryGetCaptureExpectedBuiltins(out int expectedBuiltinScores, out string? expectationError))
            {
                File.WriteAllText(Path.Combine(output, "cold-start-report.json"), JsonSerializer.Serialize(new { expectedBuiltinScores = (int?)null, failures = 1, error = expectationError, nativeSendAttempts = _nativeAttempts }, JsonDefaults.Options));
                Application.Current.Shutdown(2); return;
            }
            Width = 1460; Height = 940; UpdateLayout(); await Task.Delay(100); Capture(Path.Combine(output, "preview.png"));
            File.WriteAllText(Path.Combine(output, "cold-start-report.json"), JsonSerializer.Serialize(new { expectedBuiltinScores, scoreReads = _store.SongReads, firstPageItems = SongList.Items.Count, builtinScores = _store.Query(new(Filter: LibraryFilter.BuiltIn, Limit: 1)).Total, nativeSendAttempts = _nativeAttempts, framework = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription, coreRuntimeModule = System.Diagnostics.Process.GetCurrentProcess().Modules.Cast<System.Diagnostics.ProcessModule>().FirstOrDefault(m => m.ModuleName.Equals("coreclr.dll", StringComparison.OrdinalIgnoreCase))?.FileName, executable = Environment.ProcessPath, installedDotnetRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT"), viewport = new { width = ActualWidth, height = ActualHeight }, mode = "fresh portable release, capture only; no keyboard output" }, JsonDefaults.Options));
            Application.Current.Shutdown(_store.Query(new(Filter: LibraryFilter.BuiltIn, Limit: 1)).Total == expectedBuiltinScores && _nativeAttempts == 0 ? 0 : 1); return;
        }
        var results = new List<object>(); int failures = 0, cases = 0;
        void Check(bool ok, string why) { if (!ok) throw new Exception(why); }
        async Task Test(string name, Func<Task> action)
        {
            cases++;
            try { await action(); results.Add(new { name, status = "PASS" }); }
            catch (Exception ex) { failures++; results.Add(new { name, status = "FAIL", error = ex.ToString() }); }
        }
        void Sync(string name, Action action) => Test(name, () => { action(); return Task.CompletedTask; }).GetAwaiter().GetResult();
        void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        try
        {
            Sync("Built-in library appears in the real list control", () =>
            {
                int builtinTotal = _store.Query(new(Filter: LibraryFilter.BuiltIn, Limit: 1)).Total;
                int chineseCandidates = _store.Query(new(Filter: LibraryFilter.ChinesePop, Limit: 1)).Total;
                int chinesePopular = _store.Query(new(Filter: LibraryFilter.ChinesePopular, Limit: 1)).Total;
                var summary = _store.LanguageSummary();
                var currentPage = _libraryPage?.Items ?? Array.Empty<LibraryEntry>();
                bool firstPageChinesePopular = currentPage.All(IsChinesePopEntry) && currentPage.All(e => e.Provenance.Tags.Contains("大众优先"));
                string firstPageDetails = string.Join(";", currentPage.Take(5).Select(e => $"{e.Title}:{string.Join("|", e.Provenance.Tags)}:{string.Join("|", e.Provenance.LanguageTags)}"));
                bool firstPageOk = builtinTotal >= 30 && chineseCandidates > 0 && chinesePopular > 0 && chineseCandidates >= chinesePopular
                    && FilterCombo.SelectedIndex == ChinesePopularFilterIndex
                    && SortCombo.SelectedIndex == ChinesePrioritySortIndex && _libraryPage?.Total == chinesePopular
                    && SongList.Items.Count == currentPage.Count && currentPage.Count == Math.Min(50, chinesePopular)
                    && summary.ChinesePop == chineseCandidates && summary.ChinesePopular == chinesePopular
                    && LibraryScopeHint.Text.Contains("大众中文", StringComparison.Ordinal)
                    && firstPageChinesePopular && _keys.Count == 21;
                Check(firstPageOk, $"Chinese-pop library default / language summary: builtin={builtinTotal}; candidate={chineseCandidates}; priority={chinesePopular}; summary={summary}; hint={LibraryScopeHint.Text}; filter={FilterCombo.SelectedIndex}; sort={SortCombo.SelectedIndex}; page={_libraryPage?.Total}; items={SongList.Items.Count}; boundItems={currentPage.Count}; firstPageChinesePopular={firstPageChinesePopular}; details={firstPageDetails}; keys={_keys.Count}");
            });
            Sync("Instrument catalog and embedded official artwork load", () =>
            {
                Check(InstrumentCombo.Items.Count == 12, "instrument choices");
                foreach (var choice in InstrumentCombo.Items.OfType<InstrumentChoice>().Where(i => i.IconSource != null))
                {
                    var image = new BitmapImage(choice.IconSource!);
                    Check(image.PixelWidth >= 64 && image.PixelHeight >= 64, "image missing: " + choice.Id);
                }
            });
            await Test("Switching fourteen-key instrument updates keys, roll and saved preference", async () =>
            {
                InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "voice"); await WaitForPreparationAsync();
                Check(_keys.Count == 14 && KeysPanel.Rows == 2 && Roll.Instrument.Id == "voice" && _plan!.Notes.All(n => _keys.ContainsKey(n.Key)), "voice adaptation");
                var prefs = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(_prefsPath), JsonDefaults.Options)!;
                Check(prefs.InstrumentId == "voice", "instrument preference");
                SongList.SelectedIndex = 1; await WaitForPreparationAsync(); Check(SelectedInstrument.Id == "voice", "song switch unexpectedly changed equipped instrument");
                InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            });
            await Test("Guitar exposes seven labeled chord buttons without mistaking melody keys", async () =>
            {
                InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "euphonia"); await WaitForPreparationAsync();
                var texts = ((StackPanel)_keys['Q'].Content).Children.OfType<TextBlock>().Select(t => t.Text).ToArray();
                Check(_keys.Count == 21 && texts[1] == "C" && SelectedInstrument.Keys.Single(k => k.Key == 'Q').IsChord, "guitar chord label");
                Check(_selected!.Options.InstrumentId == "euphonia" && NativeChordCheck.IsEnabled, "guitar options not saved");
                InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            });
            await Test("Unverified drums visibly disable playback instead of emitting arbitrary pitches", async () =>
            {
                InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "djem"); await WaitForPreparationAsync();
                Check(_plan!.Notes.Count == 0 && _keys.Count == 0 && !PreviewButton.IsEnabled && !GameButton.IsEnabled && WarningsText.Text.Contains("待核验"), "unsafe drum plan");
                InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            });
            await Test("Score-hold option is wired to per-song settings", async () =>
            {
                HoldByScoreCheck.IsChecked = false; await WaitForPreparationAsync(); Check(!_selected!.Options.HoldByScore, "score hold change");
                HoldByScoreCheck.IsChecked = true; await WaitForPreparationAsync(); Check(_selected.Options.HoldByScore, "score hold restore");
            });
            await Test("Instrument changes and stop cancel a pending shortcut without native output", async () =>
            {
                _launchGate.Request(new(true, true, true, true, false, true, true));
                InstrumentCombo.SelectedIndex = 1; Check(!_launchGate.Pending && _nativeAttempts == 0, "instrument change pending");
                _launchGate.Request(new(true, true, true, true, false, true, true));
                EmergencyStop("模拟 F9"); Check(!_launchGate.Pending && _nativeAttempts == 0, "stop pending");
                InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            });
            Sync("Shift+Enter registration constants include norepeat and Return", () =>
                Check(GlobalHotkeys.StartModifiers == 0x4004 && GlobalHotkeys.StartVirtualKey == 0x0D, "incorrect shortcut registration"));
            await Test("Global-start handler also refuses native output in validation mode", async () =>
            {
                await ShortcutStartAsync(); Check(_nativeAttempts == 0 && _sink == null && _launchCancel == null && StatusText.Text.Contains("拒绝"), "shortcut bypassed test lock");
            });
            await Test("Every instrument selection uses only its own keyboard and preserves tonal source", async () =>
            {
                var original = SongParser.ToJson(_song!);
                foreach (var choice in InstrumentCombo.Items.OfType<InstrumentChoice>())
                {
                    InstrumentCombo.SelectedItem = choice; await WaitForPreparationAsync();
                    Check(_keys.Count == choice.Profile.Keys.Count && Roll.Instrument.Id == choice.Id, "layout: " + choice.Id);
                    Check(SongParser.ToJson(_song!) == original, "source mutated: " + choice.Id);
                    Check(choice.Profile.CanAutoPlay ? _plan!.Notes.All(n => _keys.ContainsKey(n.Key)) : _plan!.Notes.Count == 0, "wrong keys: " + choice.Id);
                }
                InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            });
            await Test("Parameter edits and seek cancel pending shortcut at real desktop handlers", async () =>
            {
                _launchGate.Request(new(true, true, true, true, false, true, true));
                SpeedSlider.Value = 1.05; Check(!_launchGate.Pending, "parameter edit left pending"); SpeedSlider.Value = 1; await WaitForPreparationAsync();
                _launchGate.Request(new(true, true, true, true, false, true, true));
                SeekTo(100); Check(!_launchGate.Pending && _nativeAttempts == 0, "seek left pending"); SeekTo(0);
            });
            await Test("Search and empty state through actual asynchronous pipeline", async () =>
            {
                int savedFilter = FilterCombo.SelectedIndex, savedSort = SortCombo.SelectedIndex;
                try
                {
                    // The search fixture is a teaching score, not a Chinese-pop candidate; search must cover the full catalogue.
                    FilterCombo.SelectedIndex = (int)LibraryFilter.All; SortCombo.SelectedIndex = 0; SearchBox.Clear(); await WaitForLibraryAsync();
                    SearchBox.Text = "欢乐颂"; await WaitForLibraryAsync(); Check(SongList.Items.Count == 1, "search");
                    SearchBox.Text = "不存在的曲谱__fixture"; await WaitForLibraryAsync(); Check(SongList.Items.Count == 0 && EmptyState.Visibility == Visibility.Visible, "empty state");
                }
                finally
                {
                    SearchBox.Clear(); FilterCombo.SelectedIndex = savedFilter; SortCombo.SelectedIndex = savedSort; await WaitForLibraryAsync();
                }
            });
            await Test("Chinese-pop filter and priority sort use the actual catalogue", async () =>
            {
                int savedFilter = FilterCombo.SelectedIndex, savedSort = SortCombo.SelectedIndex;
                try
                {
                    FilterCombo.SelectedIndex = ChinesePopularFilterIndex; await WaitForLibraryAsync();
                    int chinesePopular = _store.Query(new(Filter: LibraryFilter.ChinesePopular, Limit: 1)).Total;
                    int chineseCandidates = _store.Query(new(Filter: LibraryFilter.ChinesePop, Limit: 1)).Total;
                    var strictItems = SongList.Items.OfType<LibraryEntry>().ToList();
                    var invalidStrict = strictItems.Where(e => !e.Provenance.Tags.Contains("大众优先")
                        || !e.Provenance.Tags.Any(tag => tag is "中文歌曲" or "中文流行" or "中文流行候选" or "粤语歌曲" or "粤语流行" or "粤语流行候选"))
                        .Take(5).Select(e => $"{e.Id}:{string.Join("|", e.Provenance.Tags)}").ToArray();
                    Check(chinesePopular > 0 && chineseCandidates >= chinesePopular && _libraryPage?.Total == chinesePopular
                        && SongList.Items.Count == Math.Min(50, chinesePopular)
                        && strictItems.Count == SongList.Items.Count && invalidStrict.Length == 0,
                        $"Chinese-pop main filter; candidates={chineseCandidates}; popular={chinesePopular}; page={_libraryPage?.Total}; items={SongList.Items.Count}; strictItems={strictItems.Count}; invalid={string.Join(";", invalidStrict)}");
                    FilterCombo.SelectedIndex = ChinesePopFilterIndex; await WaitForLibraryAsync();
                    Check(_libraryPage?.Total == chineseCandidates && SongList.Items.Count == Math.Min(50, chineseCandidates), "Chinese-pop candidate filter");
                    FilterCombo.SelectedIndex = (int)LibraryFilter.All; SortCombo.SelectedIndex = ChinesePrioritySortIndex; await WaitForLibraryAsync();
                    Check(SongList.Items.Count == 50 && SongList.Items.OfType<LibraryEntry>().All(e =>
                        e.Provenance.Tags.Contains("中文歌曲") || e.Provenance.Tags.Contains("中文流行") || e.Provenance.Tags.Contains("粤语流行")), "Chinese-pop priority first page");
                     FilterCombo.SelectedIndex = UnknownLanguageFilterIndex; await WaitForLibraryAsync();
                     int unknownLanguage = _store.Query(new(Filter: LibraryFilter.UnknownLanguage, Limit: 1)).Total;
                     var unknownItems = SongList.Items.OfType<LibraryEntry>().ToList();
                     Check(unknownLanguage > 0 && _libraryPage?.Total == unknownLanguage
                         && unknownItems.All(e => e.Provenance.LanguageTags.Count == 0
                             || e.Provenance.LanguageTags.All(tag => tag.StartsWith("und", StringComparison.OrdinalIgnoreCase)
                                 || tag.StartsWith("unknown", StringComparison.OrdinalIgnoreCase)
                                 || tag.StartsWith("unspecified", StringComparison.OrdinalIgnoreCase))),
                         $"unknown-language filter; total={unknownLanguage}; page={_libraryPage?.Total}; items={unknownItems.Count}");
                }
                finally
                {
                    FilterCombo.SelectedIndex = savedFilter; SortCombo.SelectedIndex = savedSort; await WaitForLibraryAsync();
                }
            });
            await Test("List selection loads title and roll", async () => { SongList.SelectedIndex = 1; await WaitForPreparationAsync(); Check(_song != null && Roll.Plan?.Notes.Count > 0 && NowTitle.Text == _song.Title, "selection"); });
            await Test("Per-song speed control persists", async () => { SpeedSlider.Value = 1.5; await WaitForPreparationAsync(); var again = new LibraryStore(_store.DataDirectory, _store.BuiltInDirectory); Check(again.Entries.Single(e => e.Id == _selected!.Id).Options.Speed == 1.5, "speed persistence"); SpeedSlider.Value = 1; await WaitForPreparationAsync(); });
            await Test("BPM control changes ratio", async () => { BpmBox.Text = (_song!.Bpm * 1.2).ToString(System.Globalization.CultureInfo.InvariantCulture); Bpm_Click(this, new()); await WaitForPreparationAsync(); Check(Math.Abs(SpeedSlider.Value - 1.2) < .001, "BPM ratio"); SpeedSlider.Value = 1; await WaitForPreparationAsync(); });
            await Test("Chord and accidental controls rebuild the real plan", async () => { ChordCombo.SelectedIndex = 1; await WaitForPreparationAsync(); Check(_selected!.Options.Chords == ChordMode.Ascending, "chord mode"); AccidentalCombo.SelectedIndex = 2; await WaitForPreparationAsync(); Check(_selected.Options.Accidentals == AccidentalMode.Upper, "accidental mode"); Click(new Button()); Reset_Click(this, new()); await WaitForPreparationAsync(); });
            ParametersToggle_Click(this, new()); UpdateLayout(); await Task.Delay(80);
            await Test("Dropdown popup opens on the rendered control", async () => { ChordCombo.IsDropDownOpen = true; await Task.Delay(60); Check(ChordCombo.IsDropDownOpen, "popup did not open"); ChordCombo.IsDropDownOpen = false; });
            await Test("Slider thumb drag follows the actual WPF template", async () => { SpeedSlider.ApplyTemplate(); var track = (System.Windows.Controls.Primitives.Track)SpeedSlider.Template.FindName("PART_Track", SpeedSlider); double before = SpeedSlider.Value; track.Thumb.RaiseEvent(new System.Windows.Controls.Primitives.DragDeltaEventArgs(25, 0) { RoutedEvent = System.Windows.Controls.Primitives.Thumb.DragDeltaEvent }); Check(SpeedSlider.Value > before, "thumb drag did not update speed"); SpeedSlider.Value = 1; await WaitForPreparationAsync(); });
            ParametersClose_Click(this, new());
            await Test("Favorite view after asynchronous refresh", async () => { Click(FavoriteButton); SetPage("favorites"); await WaitForLibraryAsync(); Check(SongList.Items.Count == 1, "favorite count"); Click(FavoriteButton); SetPage("library"); await WaitForLibraryAsync(); });
            await Test("Queue view and queue flag after asynchronous refresh", async () => { Click(QueueButton); SetPage("queue"); await WaitForLibraryAsync(); Check(SongList.Items.Count == 1 && _selected!.InQueue, "queue count"); Click(QueueButton); SetPage("library"); await WaitForLibraryAsync(); });
            await Test("Playlist controls create, rename, add, remove and delete without deleting scores", async () =>
            {
                LibraryTools_Click(this, new()); PlaylistNew_Click(this, new()); PlaylistNameBox.Text = "界面测试歌单";
                PlaylistConfirm_Click(this, new()); await WaitForLibraryAsync(); string id = SelectedPlaylist!.Id!;
                Check(_store.Playlists().Any(p => p.Id == id) && PlaylistNamePopup.IsOpen == false, "create popup");
                PlaylistAdd_Click(this, new()); await WaitForLibraryAsync(); Check(SongList.Items.Count == 1, "add selected score");
                PlaylistRename_Click(this, new()); PlaylistNameBox.Text = "歌单改名"; PlaylistConfirm_Click(this, new()); await WaitForLibraryAsync();
                Check(SelectedPlaylist!.Name == "歌单改名" && SelectedPlaylist.ToString() == "歌单改名 (1)" && PlaylistCombo.ItemTemplate != null, "rename / displayed label");
                int catalogCount = _store.Count;
                PlaylistRemove_Click(this, new()); await WaitForLibraryAsync(); Check(SongList.Items.Count == 0 && _store.Count == catalogCount, "remove deleted scores");
                PlaylistDelete_Click(this, new()); await WaitForLibraryAsync(); Check(_store.Playlists().Count == 0 && _store.Count == catalogCount && SongList.Items.Count > 0, "delete");
                LibraryTools_Click(this, new());
            });
            await Test("Bulk favorite and quality filter use real selection and asynchronous query", async () =>
            {
                int savedFilter = FilterCombo.SelectedIndex, savedSort = SortCombo.SelectedIndex;
                try
                {
                    SongList.SelectedItems.Clear(); SongList.SelectedItems.Add(SongList.Items[0]); SongList.SelectedItems.Add(SongList.Items[1]);
                    BulkFavorite_Click(this, new()); await WaitForLibraryAsync(); Check(_store.Query(new(Favorites: true)).Total == 2, "bulk favorites");
                    foreach (var entry in _store.Query(new(Favorites: true)).Items) { entry.Favorite = false; _store.Save(entry); }
                    // The exercise fixtures are the original teaching scores, so the quality-filter regression covers all scores.
                    FilterCombo.SelectedIndex = (int)LibraryFilter.All; await WaitForLibraryAsync();
                    QualityCombo.SelectedIndex = 1; await WaitForLibraryAsync();
                    var timingCompared = _store.Query(new(Quality: LibraryQuality.TimingCompared));
                    Check(timingCompared.Total > 0 && SongList.Items.Count == Math.Min(50, timingCompared.Total), "timing comparison filter");
                    QualityCombo.SelectedIndex = 3; await WaitForLibraryAsync();
                    var exercises = _store.Query(new(Quality: LibraryQuality.Exercises));
                    Check(exercises.Total > 0 && SongList.Items.Count == Math.Min(50, exercises.Total)
                        && SongList.Items.OfType<LibraryEntry>().All(e => e.Provenance.Completeness == "exercise"), "exercise filter");
                    QualityCombo.SelectedIndex = 0; await WaitForLibraryAsync(); SongList.SelectedIndex = 1; await WaitForPreparationAsync();
                }
                finally
                {
                    QualityCombo.SelectedIndex = 0; FilterCombo.SelectedIndex = savedFilter; SortCombo.SelectedIndex = savedSort; await WaitForLibraryAsync();
                }
            });
            await Test("Track deselection disables both play actions", async () => { foreach (var c in TracksPanel.Children.OfType<CheckBox>()) c.IsChecked = false; await WaitForPreparationAsync(); Check(_plan!.Notes.Count == 0 && !PreviewButton.IsEnabled && !GameButton.IsEnabled, "empty tracks still playable"); foreach (var c in TracksPanel.Children.OfType<CheckBox>()) c.IsChecked = true; await WaitForPreparationAsync(); });
            Sync("Workshop validates a text score", () => { SetPage("editor"); NewScore_Click(this, new()); Check(ParseEditor().Notes.Count > 0, "editor parsing"); });
            await Test("Workshop creates a new copy via real save button", async () => { int before = _store.Entries.Count; EditorBox.Text = "TITLE=界面验证谱\nBPM=120\nFORMAT=keys\nA S D (ADG):2"; Click(EditorSaveButton); await WaitForPreparationAsync(); Check(_store.Entries.Count == before + 1 && _selected!.Title == "界面验证谱", "workshop save"); });
            await Test("File importer handles valid and invalid files without touching sources", async () =>
            {
                string good = Path.Combine(output, "fixture.txt"), bad = Path.Combine(output, "invalid.txt");
                File.WriteAllText(good, "TITLE=导入验证\nA S D"); File.WriteAllText(bad, "P");
                int before = _store.Entries.Count; await ImportFilesAsync(new[] { good, bad });
                Check(_store.Entries.Count == before + 1 && File.ReadAllText(bad) == "P" && StatusText.Text.Contains("失败 1"), "partial import");
            });
            await Test("Failed selection clears the old ready score and cannot fall back to playing it", async () =>
            {
                var bad = _store.AddSong(new() { Title = "损坏资源测试（不是收录歌曲）", Notes = [new(60,0,100)], Provenance = new() { Synthetic = true } });
                File.AppendAllText(_store.ResolvePath(bad), " "); SelectEntry(bad); await WaitForPreparationAsync();
                Check(_song == null && _plan == null && !PreviewButton.IsEnabled && !GameButton.IsEnabled && Roll.Plan == null, "previous score still armed");
                Check(_selected == bad && StatusText.Text.Contains("失败") && File.Exists(_store.ResolvePath(bad)), "failure not visible / file deleted");
                await ShortcutStartAsync(); Check(_nativeAttempts == 0, "failed score sent input"); SelectEntry(_store.Query(new(Filter: LibraryFilter.BuiltIn)).Items[0]);
                await WaitForLibraryAsync(); await WaitForPreparationAsync();
            });
            Sync("Native input structure matches Windows x64 ABI", () => Check(WindowsKeySink.InputStructureSize == 40, "INPUT size must be 40 bytes"));
            Sync("Native sink is unarmed by default and sends nothing", () => { using var sink = new WindowsKeySink(new(0, 0, "YuanShen", "invalid fixture")); bool denied = false; try { sink.Press(new[] { 'A' }); } catch { denied = true; } Check(denied && sink.SendAttempts == 0 && !GameWindows.Check(new(0, 0, "YuanShen", "fixture")).Allowed, "unarmed sink accepted input"); });
            Sync("Game action cannot arm keyboard in validation mode", () => { Click(GameButton); Check(_nativeAttempts == 0 && _sink == null && _launchCancel == null && StatusText.Text.Contains("拒绝"), "keyboard output occurred"); });
            Sync("Settings / help navigation shows the correct page", () => { Click(NavSettings); Check(SettingsPage.Visibility == Visibility.Visible && Workbench.Visibility == Visibility.Collapsed, "settings navigation"); Click(NavHelp); Check(HelpPage.Visibility == Visibility.Visible, "help navigation"); Click(NavLibrary); });
            await Test("Local WAV loads in WPF MediaPlayer, pause and seek work (muted)", async () =>
            {
                await WaitForPreparationAsync(); VolumeSlider.Value = 0; await StartPreviewAsync();
                for (int i = 0; i < 100 && !_previewActive; i++) await Task.Delay(50);
                Check(_previewActive, "MediaPlayer did not open the local WAV: " + StatusText.Text);
                await Task.Delay(250); UpdatePlaybackView(); Check(_position > 0, "preview position did not advance");
                Click(PauseButton); Check(_previewPaused, "pause"); double position = _media!.Position.TotalMilliseconds;
                await Task.Delay(100); Check(Math.Abs(_media.Position.TotalMilliseconds - position) < 35, "paused position moved");
                Click(PauseButton); ProgressSlider.Value = 1000; Check(Math.Abs(_media.Position.TotalMilliseconds - 1000) < 60, "seek");
                Click(StopButton); Check(!_previewActive && _nativeAttempts == 0, "stop / native safety");
            });
            Sync("Preview timer tolerates invalid uncommitted loop text", () =>
            {
                try { _media = new MediaPlayer(); _previewActive = true; LoopStartBox.Text = "not a number"; UpdatePlaybackView(); }
                finally { EmergencyStop(); LoopStartBox.Text = "0"; }
            });
            SelectEntry(_store.Entries[0]); Reset_Click(this, new()); await WaitForPreparationAsync(); SearchBox.Clear(); await WaitForLibraryAsync();
            await Test("Expanded library management stays inside the minimum viewport", async () =>
            {
                Width = 1120; Height = 780; SetPage("library"); await WaitForLibraryAsync();
                if (LibraryToolsPanel.Visibility != Visibility.Visible) LibraryTools_Click(this,new());
                UpdateLayout(); await Task.Delay(100);
                foreach (var control in new FrameworkElement[] { QualityCombo, PlaylistCombo, PlaylistNewButton, PlaylistRenameButton, PlaylistDeleteButton, PlaylistAddButton, PlaylistRemoveButton, BulkFavoriteButton, PreviousPageButton, NextPageButton })
                {
                    var point = control.TransformToAncestor(LibraryPanel).Transform(new Point());
                    Check(point.X >= -1 && point.Y >= -1 && point.X + control.ActualWidth <= LibraryPanel.ActualWidth + 1 && point.Y + control.ActualHeight <= LibraryPanel.ActualHeight + 1, "management control clipped: " + control.Name);
                }
                Capture(Path.Combine(output,"library-management-1120.png")); Check(SongList.ActualHeight > 80,"management consumes full list: " + SongList.ActualHeight);
                LibraryTools_Click(this,new()); Width=1460; Height=940; UpdateLayout();
            });
            await ValidateAppearanceAsync(output, Test, Sync, Check);
            SetPage("library"); VolumeSlider.Value = .65;
            Width = 1460; Height = 940; UpdateLayout(); await Task.Delay(100); Capture(Path.Combine(output, "workbench-1460.png"));
            Sync("Persistent controls fit at 1460x940", () => CheckFooterBounds());
            Sync("All three keyboard rows fit without initial scrolling at 1460x940", () =>
            {
                var bottom = KeysPanel.TransformToAncestor(WorkbenchScroll).Transform(new Point(0, KeysPanel.ActualHeight));
                Check(bottom.Y <= WorkbenchScroll.ActualHeight - 2, "keyboard third row clipped: " + bottom.Y + " / available " + WorkbenchScroll.ActualHeight);
            });
            Sync("Time labels do not overlap at 1460x940", () => CheckTimelineLabels());
            Width = 1080; Height = 720; UpdateLayout(); await Task.Delay(100); Capture(Path.Combine(output, "workbench-1080.png"));
            Sync("Persistent controls fit at 1080x720", () => CheckFooterBounds());
            Sync("Time labels do not overlap at 1080x720", () => CheckTimelineLabels());
            Sync("Long-score labels remain spaced at minimum width", () =>
            {
                var savedPlan = Roll.Plan; double savedWindow = Roll.WindowSeconds, savedPosition = Roll.PositionMs;
                try
                {
                    Roll.Plan = new([], 7200000, new(0, 0, 0, 0, 0, 0, 0), []); Roll.WindowSeconds = 0; Roll.PositionMs = 0;
                    Roll.InvalidateVisual(); Capture(Path.Combine(output, "timeline-long-score.png")); CheckTimelineLabels();
                }
                finally { Roll.Plan = savedPlan; Roll.WindowSeconds = savedWindow; Roll.PositionMs = savedPosition; Roll.InvalidateVisual(); }
            });
            Width = 1460; Height = 940; UpdateLayout();
            InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "euphonia"); await WaitForPreparationAsync();
            await Task.Delay(80); Capture(Path.Combine(output, "instrument-guitar-1460.png"));
            InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "voice"); await WaitForPreparationAsync();
            await Task.Delay(80); Capture(Path.Combine(output, "instrument-voice-1460.png"));
            InstrumentCombo.SelectedIndex = 0; await WaitForPreparationAsync();
            SetPage("editor"); NewScore_Click(this, new()); Width = 1460; Height = 940; UpdateLayout(); await Task.Delay(100); Capture(Path.Combine(output, "workshop.png"));
            SetPage("settings"); UpdateLayout(); await Task.Delay(100); Capture(Path.Combine(output, "safety-settings.png"));
            await ValidateMetadataAsync(output, Test, Check);
            Sync("No unhandled Dispatcher exception or native output", () => Check(_validationUnhandled.Count == 0 && _nativeAttempts == 0, string.Join(";", _validationUnhandled)));
        }
        catch (Exception ex) { failures++; results.Add(new { name = "validation driver", status = "FAIL", error = ex.ToString() }); }
        finally
        {
            EmergencyStop("自测结束");
            var dpi = VisualTreeHelper.GetDpi(this);
            File.WriteAllText(Path.Combine(output, "ui-test-report.json"), JsonSerializer.Serialize(new { cases, failures, nativeSendAttempts = _nativeAttempts, previewCleanupWarnings = _previewCleanupWarnings, dpi = dpi.PixelsPerDip, workingArea = SystemParameters.WorkArea.ToString(), screenshots = _captureViewports, appearanceValidation = "built-ins, local import, image limits, privacy, contrast, persistence, layout and drawer; isolated fixtures only", physicalAudioOutput = "NOT TESTED; preview media path tested muted", gamePlayback = "NOT TESTED; native input prohibited in validation mode", results }, JsonDefaults.Options));
            Application.Current.Shutdown(failures == 0 ? 0 : 1);
        }
    }
    private void CheckTimelineLabels()
    {
        var labels = Roll.TimeLabelBounds;
        if (labels.Count < 2) throw new Exception("Timeline labels were not rendered");
        for (int i = 0; i < labels.Count; i++)
        {
            if (labels[i].Left < 37 - .01 || labels[i].Right > Roll.ActualWidth - 12 + .01)
                throw new Exception("Timeline label outside axis bounds");
            if (i > 0 && labels[i].Left - labels[i - 1].Right < 8 - .01)
                throw new Exception($"Timeline labels overlap or lack 8 DIP spacing: {labels[i].Left - labels[i - 1].Right:0.##} DIP");
        }
    }
    private void CheckFooterBounds()
    {
        var root = (FrameworkElement)Content;
        foreach (var control in new FrameworkElement[] { PreviewButton, PauseButton, StopButton, GameButton, ProgressSlider })
        {
            var point = control.TransformToAncestor(root).Transform(new Point());
            if (!control.IsVisible || point.X < 0 || point.Y < 0 || point.X + control.ActualWidth > root.ActualWidth + 1 || point.Y + control.ActualHeight > root.ActualHeight + 1)
                throw new Exception("Persistent control outside viewport: " + control.Name);
        }
    }
    private readonly List<object> _captureViewports = [];
    private void Capture(string path)
    {
        var root = (FrameworkElement)Content; root.UpdateLayout(); var dpi = VisualTreeHelper.GetDpi(root);
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth * dpi.DpiScaleX), (int)Math.Ceiling(root.ActualHeight * dpi.DpiScaleY), dpi.PixelsPerInchX, dpi.PixelsPerInchY, PixelFormats.Pbgra32);
        bitmap.Render(root);
        _captureViewports.Add(new { file = Path.GetFileName(path), requestedWidth = Width, requestedHeight = Height, actualWidth = ActualWidth, actualHeight = ActualHeight, contentWidth = root.ActualWidth, contentHeight = root.ActualHeight, pixelsWidth = bitmap.PixelWidth, pixelsHeight = bitmap.PixelHeight, dpi = dpi.PixelsPerDip });
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = File.Create(path); encoder.Save(stream);
    }
}
