using System.Diagnostics;
using System.Text.Json;
using QinBan.Core;

internal static class ScorePreparationTests
{
    public static async Task RunAsync(string output, Func<string, Func<Task>, Task> test, Action<bool, string> check)
    {
        SongDocument Fixture(int count = 1) => new() { Title = "Preparation fixture - not a song", LengthMs = Math.Max(500, count * 8d),
            Notes = Enumerable.Range(0, count).Select(i => new NoteEvent(60 + i % 7, i * 8d, 7)).ToList(), Provenance = new() { Synthetic = true } };
        await test("Preparation runs off caller/UI thread and preserves options snapshot/source", async () =>
        {
            int caller = Environment.CurrentManagedThreadId; var preparer = new ScorePreparer(); var options = new PlayOptions { Speed = 1.5, Tracks = [0] }; var source = Fixture();
            using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
            var task = preparer.PrepareAsync(() => { entered.Set(); if (!release.Wait(5000)) throw new TimeoutException(); return source; }, options);
            check(entered.Wait(5000), "worker not started"); options.Speed = 3; options.Tracks!.Clear(); release.Set();
            var result = await task.WaitAsync(TimeSpan.FromSeconds(10));
            check(result.Options.Speed == 1.5 && result.Options.Tracks!.Contains(0), "mutable options escaped");
            check(result.Song == source && source.Notes[0].StartMs == 0 && source.Notes[0].DurationMs == 7, "source changed");
            check(result.WorkerThreadId != caller && result.PreparationMs >= 0, "diagnostics absent");
        });
        await test("Preparation is single-flight; cancelled queued requests never load", async () =>
        {
            var preparer = new ScorePreparer(); using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
            int active = 0, peak = 0, cancelledLoads = 0;
            SongDocument Load(bool block) { int current = Interlocked.Increment(ref active); peak = Math.Max(peak, current); if (block) { entered.Set(); if (!release.Wait(5000)) throw new TimeoutException(); } Interlocked.Decrement(ref active); return Fixture(); }
            var first = preparer.PrepareAsync(() => Load(true), new()); check(entered.Wait(5000), "no first worker");
            using var cancel = new CancellationTokenSource(); var queued = preparer.PrepareAsync(() => { ++cancelledLoads; return Fixture(); }, new(), cancel.Token);
            var last = preparer.PrepareAsync(() => Load(false), new()); cancel.Cancel(); release.Set();
            bool cancelled = false; try { await queued; } catch (OperationCanceledException) { cancelled = true; }
            await Task.WhenAll(first, last).WaitAsync(TimeSpan.FromSeconds(10));
            check(cancelled && cancelledLoads == 0 && peak == 1, "queued cancellation or single flight failed");
        });
        await test("Preparation cancellation/failure release worker for the next score", async () =>
        {
            var preparer = new ScorePreparer(); using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
            using var cancel = new CancellationTokenSource(); var task = preparer.PrepareAsync(() => { entered.Set(); if (!release.Wait(5000)) throw new TimeoutException(); return Fixture(10000); }, new(), cancel.Token);
            check(entered.Wait(5000), "no worker"); cancel.Cancel(); release.Set(); bool cancelled = false;
            try { await task; } catch (OperationCanceledException) { cancelled = true; } check(cancelled, "post-read cancellation ignored");
            bool failed = false; try { await preparer.PrepareAsync(() => throw new FormatException("invalid fixture"), new()); } catch (FormatException) { failed = true; }
            check(failed && (await preparer.PrepareAsync(() => Fixture(), new())).Plan.Notes.Count == 1, "worker not reusable");
            int loads = 0; using var before = new CancellationTokenSource(); before.Cancel();
            try { await preparer.PrepareAsync(() => { ++loads; return Fixture(); }, new(), before.Token); } catch (OperationCanceledException) { }
            check(loads == 0, "pre-cancelled loader ran");
        });
        var observations = new List<object>();
        foreach (int count in new[] { 10000, 100000 }) await test($"Preparation supports bounded synthetic {count}-note input", async () =>
        {
            var song = Fixture(count); var watch = Stopwatch.StartNew(); var prepared = await new ScorePreparer().PrepareAsync(() => song, new()).WaitAsync(TimeSpan.FromSeconds(30));
            check(prepared.Plan.Notes.Count == count && prepared.Tracks.Single().NoteCount == count, "large source truncated");
            observations.Add(new { notes = count, elapsedMs = watch.Elapsed.TotalMilliseconds, prepared.PreparationMs, workerThread = prepared.WorkerThreadId });
        });
        await test("Mapping honours pre-cancellation before any work", () =>
        {
            using var cancellation = new CancellationTokenSource(); cancellation.Cancel(); bool cancelled = false;
            try { GameMapping.Build(Fixture(), new(), cancellation.Token); } catch (OperationCanceledException) { cancelled = true; }
            check(cancelled, "mapping did not cancel"); return Task.CompletedTask;
        });
        File.WriteAllText(Path.Combine(output, "preparation-core-observations.json"), JsonSerializer.Serialize(new { kind = "synthetic note fixtures; not songs or musical validation", observations }, JsonDefaults.Options));
    }
}
