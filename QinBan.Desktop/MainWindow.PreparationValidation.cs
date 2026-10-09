using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private async Task RunPreparationValidationAsync()
    {
        string output = Path.GetDirectoryName(_store.DataDirectory)!;
        var results = new List<object>(); var observations = new List<object>(); int failures = 0;
        void Check(bool ok, string why) { if (!ok) throw new Exception(why); }
        async Task Test(string name, Func<Task> action)
        {
            var watch = Stopwatch.StartNew();
            try { await action(); results.Add(new { name, status = "PASS", milliseconds = watch.Elapsed.TotalMilliseconds }); }
            catch (Exception ex) { ++failures; results.Add(new { name, status = "FAIL", error = ex.ToString(), milliseconds = watch.Elapsed.TotalMilliseconds }); }
        }
        LibraryEntry AddFixture(int count) => _store.AddSong(new() { Title = $"Synthetic preparation fixture {count} (NOT A SONG)", LengthMs = count * 8d,
            Notes = Enumerable.Range(0, count).Select(i => new NoteEvent(60 + i % 7, i * 8d, 7)).ToList(), Provenance = new() { Synthetic = true } });
        int uiThread = Environment.CurrentManagedThreadId;
        var small = AddFixture(10000); var large = AddFixture(100000);
        await Test("Pending score cannot queue preview or game output", async () =>
        {
            SelectEntry(large); Check(_preparing && _plan == null && !PreviewButton.IsEnabled, "old plan retained while pending");
            await StartPreviewAsync(); Check(!_rendering && _media == null && StatusText.Text.Contains("准备"), "preview queued");
            await ShortcutStartAsync(); Check(!_launchGate.Pending && _sink == null && _nativeAttempts == 0, "game start queued");
            await WaitForPreparationAsync(); Check(_plan!.Notes.Count == 100000 && !_previewActive && !_rendering, "pending start replayed after preparation");
        });
        foreach (var entry in new[] { small, large }) await Test($"Real async desktop load/map/render of {entry.NotesCount} synthetic notes", async () =>
        {
            Width = 1460; Height = 940; UpdateLayout(); await Task.Delay(100);
            var gaps = new List<double>(); var steps = new List<object>(); var watch = Stopwatch.StartNew(); double previous = 0;
            var heartbeat = new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(16) };
            heartbeat.Tick += (_, _) => { double now = watch.Elapsed.TotalMilliseconds; gaps.Add(now - previous); previous = now; }; heartbeat.Start();
            double readyMs;
            try
            {
                SelectEntry(entry); await WaitForPreparationAsync(); readyMs = watch.Elapsed.TotalMilliseconds;
                Check(_song != null && _plan != null && _plan.Notes.Count == entry.NotesCount && _lastPreparedScore!.WorkerThreadId != uiThread, "map not background / truncated");
                UpdateLayout();
                // Include real playback-view/timeline work, then let the dispatcher schedule heartbeat callbacks.
                for (int i = 0; i < 12; i++)
                {
                    double before = watch.Elapsed.TotalMilliseconds; _position = i * 25000 % _plan!.DurationMs; UpdatePlaybackView(); Roll.InvalidateVisual();
                    double updateMs = watch.Elapsed.TotalMilliseconds - before; await Task.Delay(20);
                    steps.Add(new { frame = i, atMs = before, updateMs, throughDispatcherAndRenderMs = watch.Elapsed.TotalMilliseconds - before });
                }
            }
            finally { heartbeat.Stop(); }
            Check(gaps.Count >= 5, "insufficient dispatcher observation");
            double maximum = gaps.Max();
            Capture(Path.Combine(output, $"preparation-{entry.NotesCount}.png"));
            observations.Add(new { notes = entry.NotesCount, selectionToReadyMs = readyMs, workerThread = _lastPreparedScore!.WorkerThreadId,
                heartbeatSamples = gaps.Count, steps, gaps, denseDrawRectangles = Roll.DrawnNoteRectangles, maxDispatcherGapMs = maximum, p95DispatcherGapMs = gaps.Order().ElementAt((int)Math.Ceiling(gaps.Count * .95) - 1),
                workingSetMiB = Process.GetCurrentProcess().WorkingSet64 / 1048576d, frameWork = "actual playback-view update and timeline rendering; fixture file creation, window resize and PNG encoding excluded" });
            Check(Roll.DrawnNoteRectangles is > 0 and < 100, "dense visualization did not coalesce overlapping geometries");
            Check(maximum < 750, "dispatcher stalled for >=750ms on this run");
        });
        await Test("Rapid selection/options/instrument changes apply only the last request", async () =>
        {
            SelectEntry(large); SelectEntry(small); SpeedSlider.Value = 1.2;
            InstrumentCombo.SelectedItem = InstrumentCombo.Items.OfType<InstrumentChoice>().First(i => i.Id == "voice");
            InstrumentCombo.SelectedIndex = 0; SpeedSlider.Value = 1.25; await WaitForPreparationAsync();
            Check(_selected == small && _song!.Title == small.Title && _plan!.Notes.Count == 10000 && _preparedOptions!.Speed == 1.25 && _preparedOptions.InstrumentId == "windsong", "stale request applied");
            Check(small.Options.Speed == 1.25 && _store.LoadSong(small).Notes.Count == 10000, "latest options/source not persisted");
        });
        await Test("F9/stop cancels pending preparation and never arms its eventual result", async () =>
        {
            SelectEntry(large); EmergencyStop("模拟 F9 取消准备"); await WaitForPreparationAsync();
            Check(!_preparing && _plan == null && _preparedOptions == null && !PreviewButton.IsEnabled && Roll.Plan == null, "cancelled result armed");
            await StartPreviewAsync(); Check(!_rendering && _media == null, "cancelled score previewed");
            SelectEntry(small); await WaitForPreparationAsync(); Check(_plan!.Notes.Count == 10000, "cannot recover after cancel");
        });
        await Test("Bad source never falls back to previous ready score", async () =>
        {
            var bad = AddFixture(1); string path = _store.ResolvePath(bad); File.AppendAllText(path, "hash mismatch");
            SelectEntry(bad); await WaitForPreparationAsync();
            Check(_song == null && _plan == null && !PreviewButton.IsEnabled && StatusText.Text.Contains("失败") && File.Exists(path), "bad source armed / silently removed");
            SelectEntry(small); await WaitForPreparationAsync(); Check(_plan!.Notes.Count == 10000, "failure did not release preparation gate");
        });
        await Test("Cancelled preview render cannot overwrite the new session and cleans owned WAVs", async () =>
        {
            var first = StartPreviewAsync(); EmergencyStop("取消正在生成的长谱试听");
            var note = new PlannedNote(60, 'A', 0, 50, 180, 90, 0);
            var second = StartPreviewAsync(new([note], 300, new(1, 1, 0, 0, 0, 0, 0), []));
            VolumeSlider.Value = 0; await Task.WhenAll(first, second).WaitAsync(TimeSpan.FromSeconds(30));
            for (int i = 0; i < 30 && !_previewActive; i++) await Task.Delay(20);
            Check(_previewActive && !_rendering, "old cancelled render reset new preview"); EmergencyStop("结束隔离试听测试");
            string folder = Path.Combine(_store.DataDirectory, "preview");
            Check(!Directory.Exists(folder) || Directory.GetFiles(folder).Length == 0, "owned preview WAV leaked");
            Check(_previewCleanupWarnings.Count == 0, string.Join(";", _previewCleanupWarnings));
        });
        EmergencyStop("大谱验证结束");
        File.WriteAllText(Path.Combine(output, "preparation-ui-report.json"), JsonSerializer.Serialize(new { recordedAtUtc = DateTimeOffset.UtcNow, failures, nativeSendAttempts = _nativeAttempts,
            actualSongsAdded = 0, dataset = "isolated 10k/100k-note self-authored fixtures; never ship as real music", uiThread, observations,
            audioDevice = "muted MediaPlayer session test; physical sound NOT TESTED", cleanupWarnings = _previewCleanupWarnings, unhandled = _validationUnhandled, results }, JsonDefaults.Options));
        Application.Current.Shutdown(failures == 0 && _nativeAttempts == 0 && _validationUnhandled.Count == 0 ? 0 : 1);
    }
}
