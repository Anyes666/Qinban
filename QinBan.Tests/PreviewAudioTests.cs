using System.Diagnostics;
using System.Text;
using QinBan.Core;

static class PreviewAudioTests
{
    // Matches Program.cs's Sync/Check delegates; no entrypoint or real keyboard is needed.
    public static void Run(string fixtures, Action<string, Action> test, Action<bool, string> check)
    {
        string Root()
        {
            string root = Path.Combine(fixtures, "preview-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            return root;
        }
        void OnlyFiles(string root, params string[] names)
        {
            var actual = Directory.GetFiles(root).Select(Path.GetFileName).OrderBy(n => n).ToArray();
            check(actual.SequenceEqual(names.OrderBy(n => n)), "unexpected/missing files: " + string.Join(", ", actual));
        }
        void Expect<T>(Action action) where T : Exception
        {
            var error = Capture(action);
            check(error is T, $"Expected {typeof(T).Name}, got {error?.GetType().Name ?? "success"}");
        }
        string SeedForeignTemporaryFile(string root)
        {
            string name = ".qinban-preview-" + Guid.NewGuid().ToString("N") + ".float.tmp";
            WriteNew(Path.Combine(root, name), Encoding.UTF8.GetBytes("unrelated UUID file: keep"));
            return name;
        }
        void ForeignFileIntact(string root, string name) =>
            check(File.ReadAllText(Path.Combine(root, name)) == "unrelated UUID file: keep", "foreign temporary file was changed");

        test("Preview WAV retains complete RIFF / mono 22050Hz / 16-bit PCM format", () =>
        {
            string root = Root(), path = Path.Combine(root, "format.wav");
            var plan = Plan(new PlannedNote(60, 'A', 0, 100, 200, 100, 0), new(64, 'D', 250, 100, 150, 100, 0));
            double duration = PreviewAudio.WriteWave(plan, path);
            byte[] bytes = File.ReadAllBytes(path);
            check(duration == plan.DurationMs + 450, "duration padding changed");
            Header(bytes, duration, check);
            check(bytes.Skip(44).Any(b => b != 0), "silent PCM");
            OnlyFiles(root, "format.wav");
        });

        test("Preview block boundaries and one global peak gain match original PCM byte-for-byte", () =>
        {
            string root = Root(), path = Path.Combine(root, "global.wav");
            var notes = new List<PlannedNote>
            {
                new(67, 'G', 4400.25, 200, 350.5, 45, 0), // Deliberately not sorted.
                new(60, 'A', .3, 200, 900.7, 40, 0),
                new(62, 'S', 1300.5, 200, 3500.25, 90, 0, [62, 65, 69], true)
            };
            notes.AddRange(Enumerable.Range(0, 18).Select(_ => new PlannedNote(60, 'A', 2100.75, 200, 550.5, 127, 0, Sustain: true)));
            var plan = Plan(notes.ToArray());
            var reference = ReferencePcm(plan);
            check(reference.Peak > .94, "fixture did not exercise global normalization");
            PreviewAudio.WriteWave(plan, path);
            byte[] actual = File.ReadAllBytes(path);
            check(actual.AsSpan(44).SequenceEqual(reference.Pcm), "PCM changed across blocks / quiet passages / peak normalization");
            check(Enumerable.Range(0, reference.Pcm.Length / 2).Max(i => Math.Abs((int)BitConverter.ToInt16(reference.Pcm, i * 2))) <= 30801, "global gain ceiling changed");
            OnlyFiles(root, "global.wav");
        });

        test("Preview below-threshold gain and short / sustained envelopes match original PCM", () =>
        {
            string root = Root(), path = Path.Combine(root, "envelope.wav");
            var plan = Plan(new PlannedNote(60, 'A', 0, 200, 3050.5, 75, 0, Sustain: true), new(64, 'D', 3500.25, 40, 25.75, 60, 0));
            var reference = ReferencePcm(plan);
            check(reference.Peak < .94, "fixture unexpectedly normalized");
            PreviewAudio.WriteWave(plan, path);
            check(File.ReadAllBytes(path).AsSpan(44).SequenceEqual(reference.Pcm), "envelope / release / quiet gain changed");
            double Energy(int ms) => Enumerable.Range(ms * PreviewAudio.SampleRate / 1000, 500)
                .Average(i => Math.Abs((double)BitConverter.ToInt16(reference.Pcm, i * 2)));
            check(Energy(2000) > 50 && Energy(3300) == 0 && Energy(3750) == 0, "long note / release / rests changed");
            OnlyFiles(root, "envelope.wav");
        });

        test("Preview ten-minute output has bounded sample buffers and allocation", () =>
        {
            string root = Root(), path = Path.Combine(root, "ten-minutes.wav");
            // Only a short note near the end: duration still exercises every float / PCM block.
            var plan = Plan(new PlannedNote(60, 'A', PreviewAudio.MaxPreviewMs - 200, 100, 1000, 80, 0, Sustain: true));
            long before = GC.GetAllocatedBytesForCurrentThread();
            double duration = PreviewAudio.WriteWave(plan, path);
            long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
            check(PreviewAudio.MaxSampleBufferBytes == 192 * 1024 && PreviewAudio.MaxSampleBufferBytes <= 1024 * 1024, "sample buffer cap");
            check(allocated < 1024 * 1024, "ten-minute sparse render allocated " + allocated + " bytes");
            check(duration == PreviewAudio.MaxPreviewMs, "ten-minute cap changed");
            using (var stream = File.OpenRead(path))
            {
                var header = new byte[44]; stream.ReadExactly(header);
                check(stream.Length == 44L + (long)Math.Ceiling(duration * PreviewAudio.SampleRate / 1000) * 2, "truncated ten-minute WAV");
                check(BitConverter.ToInt32(header, 40) == stream.Length - 44, "ten-minute data header");
            }
            Console.WriteLine($"EVIDENCE ten-minute render: sample buffers={PreviewAudio.MaxSampleBufferBytes} bytes; thread allocations={allocated} bytes");
            OnlyFiles(root, "ten-minutes.wav");
        });

        test("Preview empty-plan failure does not create or remove files", () =>
        {
            string root = Root(), foreign = SeedForeignTemporaryFile(root);
            Expect<InvalidOperationException>(() => PreviewAudio.WriteWave(Plan(), Path.Combine(root, "empty.wav")));
            ForeignFileIntact(root, foreign); OnlyFiles(root, foreign);
        });

        test("Preview refuses existing unlocked or exclusively locked files without overwriting", () =>
        {
            string root = Root(), path = Path.Combine(root, "original.wav"), foreign = SeedForeignTemporaryFile(root);
            byte[] original = Encoding.UTF8.GetBytes("user's existing WAV must remain byte-identical"); WriteNew(path, original);
            Expect<IOException>(() => PreviewAudio.WriteWave(ShortPlan(), path));
            using (var locked = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                Expect<IOException>(() => PreviewAudio.WriteWave(ShortPlan(), path));
            check(File.ReadAllBytes(path).SequenceEqual(original), "existing file overwritten");
            ForeignFileIntact(root, foreign); OnlyFiles(root, "original.wav", foreign);
        });

        test("Preview directory destination is rejected and directory contents remain", () =>
        {
            string root = Root(), path = Path.Combine(root, "directory.wav"); Directory.CreateDirectory(path);
            WriteNew(Path.Combine(path, "keep.txt"), Encoding.UTF8.GetBytes("keep directory"));
            Expect<IOException>(() => PreviewAudio.WriteWave(ShortPlan(), path));
            check(Directory.Exists(path) && File.ReadAllText(Path.Combine(path, "keep.txt")) == "keep directory", "directory was changed");
            OnlyFiles(root);
        });

        test("Preview missing or file-valued parent fails without creating parent or touching data", () =>
        {
            string root = Root(), missing = Path.Combine(root, "missing"), blocker = Path.Combine(root, "parent-file");
            WriteNew(blocker, Encoding.UTF8.GetBytes("parent blocker"));
            Expect<DirectoryNotFoundException>(() => PreviewAudio.WriteWave(ShortPlan(), Path.Combine(missing, "out.wav")));
            Expect<DirectoryNotFoundException>(() => PreviewAudio.WriteWave(ShortPlan(), Path.Combine(blocker, "out.wav")));
            check(!Directory.Exists(missing) && File.ReadAllText(blocker) == "parent blocker", "parent changed");
            OnlyFiles(root, "parent-file");
        });

        test("Preview pre-cancellation leaves no output and retains an existing destination", () =>
        {
            string root = Root(), path = Path.Combine(root, "cancel.wav"), old = Path.Combine(root, "existing.wav");
            WriteNew(old, Encoding.UTF8.GetBytes("existing before cancellation"));
            using var cancel = new CancellationTokenSource(); cancel.Cancel();
            Expect<OperationCanceledException>(() => PreviewAudio.WriteWave(ShortPlan(), path, cancel.Token));
            Expect<OperationCanceledException>(() => PreviewAudio.WriteWave(ShortPlan(), old, cancel.Token));
            check(!File.Exists(path) && File.ReadAllText(old) == "existing before cancellation", "cancel created / overwrote output");
            OnlyFiles(root, "existing.wav");
        });

        foreach (bool duringPcm in new[] { false, true })
        {
            test(duringPcm ? "Preview cancellation after PCM bytes are written removes only owned UUID files"
                : "Preview cancellation after float bytes are written removes only owned UUID files", () =>
            {
                string root = Root(), path = Path.Combine(root, "cancelled.wav"), foreign = SeedForeignTemporaryFile(root);
                using var cancel = new CancellationTokenSource();
                var render = Start(LongPlan(), path, cancel.Token);
                string? observed;
                try { observed = WaitForFile(render, root, duringPcm ? "*.wav.tmp" : "*.float.tmp", duringPcm ? 44 : 0, foreign); }
                finally { cancel.Cancel(); }
                var error = Capture(() => render.GetAwaiter().GetResult());
                check(observed != null, "did not observe audio-writing stage before cancelling");
                check(error is OperationCanceledException, "cancellation did not propagate: " + error?.GetType().Name);
                check(!File.Exists(path), "cancel left final WAV");
                ForeignFileIntact(root, foreign); OnlyFiles(root, foreign);
                Console.WriteLine("EVIDENCE cancellation after " + (duringPcm ? "WAV PCM > 44 bytes" : "float data > 0 bytes") + ": no final WAV / owned temporary files; unrelated UUID preserved");
            });
        }

        test("Preview destination created during rendering wins; failed publication leaves no owned files", () =>
        {
            string root = Root(), path = Path.Combine(root, "racing.wav");
            using var cancel = new CancellationTokenSource();
            var render = Start(LongPlan(), path, cancel.Token);
            string? observed = WaitForFile(render, root, "*.float.tmp", 0);
            if (observed == null) cancel.Cancel();
            else WriteNew(path, Encoding.UTF8.GetBytes("created by another writer"));
            var error = Capture(() => render.GetAwaiter().GetResult());
            check(observed != null && error is IOException, "publish conflict was not tested / rejected");
            check(File.ReadAllText(path) == "created by another writer", "racing destination overwritten");
            OnlyFiles(root, "racing.wav");
        });

        test("Preview failed CreateNew on staged WAV retains that unowned UUID file", () =>
        {
            string root = Root(), path = Path.Combine(root, "blocked.wav");
            using var cancel = new CancellationTokenSource();
            var render = Start(LongPlan(), path, cancel.Token);
            string? observed = WaitForFile(render, root, "*.float.tmp", 0);
            string? blocker = observed?.Replace(".float.tmp", ".wav.tmp", StringComparison.Ordinal);
            if (blocker == null) cancel.Cancel();
            else WriteNew(blocker, Encoding.UTF8.GetBytes("unowned UUID collision"));
            var error = Capture(() => render.GetAwaiter().GetResult());
            check(blocker != null && error is IOException, "staging failure was not tested / rejected");
            check(!File.Exists(path) && File.ReadAllText(blocker!) == "unowned UUID collision", "unowned staging file deleted / final output created");
            OnlyFiles(root, Path.GetFileName(blocker!));
        });

        test("Preview synthesis failure cleans its float file, without deleting unrelated files", () =>
        {
            string root = Root(), path = Path.Combine(root, "bad-note.wav"), foreign = SeedForeignTemporaryFile(root);
            var bad = Plan(new PlannedNote(60, 'A', -100, 100, 200, 80, 0));
            Expect<ArgumentOutOfRangeException>(() => PreviewAudio.WriteWave(bad, path));
            check(!File.Exists(path), "synthesis failure left output");
            ForeignFileIntact(root, foreign); OnlyFiles(root, foreign);
        });

        test("Preview concurrent different paths remain independent and match original PCM", () =>
        {
            string root = Root(), other = Root(), a = Path.Combine(root, "a.wav"), b = Path.Combine(root, "b.wav"), c = Path.Combine(other, "c.wav");
            var first = ShortPlan(); var second = Plan(new PlannedNote(67, 'G', 100.25, 300, 3500, 70, 0, [67, 71, 74], true));
            var tasks = new[] { Start(first, a), Start(second, b), Start(first, c) };
            Task.WaitAll(tasks);
            check(File.ReadAllBytes(a).AsSpan(44).SequenceEqual(ReferencePcm(first).Pcm), "first concurrent output differs");
            check(File.ReadAllBytes(b).AsSpan(44).SequenceEqual(ReferencePcm(second).Pcm), "second concurrent output differs");
            check(File.ReadAllBytes(a).SequenceEqual(File.ReadAllBytes(c)), "different-directory render differs");
            OnlyFiles(root, "a.wav", "b.wav"); OnlyFiles(other, "c.wav");
        });

        test("Preview cancelling one render cannot delete another completed render in the same directory", () =>
        {
            string root = Root(), a = Path.Combine(root, "cancel-one.wav"), b = Path.Combine(root, "keep-other.wav");
            using var cancel = new CancellationTokenSource();
            var render = Start(LongPlan(), a, cancel.Token);
            string? observed;
            try
            {
                observed = WaitForFile(render, root, "*.float.tmp", 0);
                PreviewAudio.WriteWave(ShortPlan(), b);
            }
            finally { cancel.Cancel(); }
            var error = Capture(() => render.GetAwaiter().GetResult());
            check(observed != null && error is OperationCanceledException && !File.Exists(a), "first render not cancelled cleanly");
            check(File.ReadAllBytes(b).AsSpan(44).SequenceEqual(ReferencePcm(ShortPlan()).Pcm), "other render changed");
            OnlyFiles(root, "keep-other.wav");
        });
    }

    private static PlaybackPlan Plan(params PlannedNote[] notes) => new(notes.ToList(),
        notes.Length == 0 ? 0 : notes.Max(n => n.StartMs + n.SoundMs), new(notes.Length, notes.Length, 0, 0, 0, 0, 0), []);
    private static PlaybackPlan ShortPlan() => Plan(new PlannedNote(60, 'A', 0, 200, 200, 80, 0));
    private static PlaybackPlan LongPlan() => Plan(new PlannedNote(60, 'A', 0, 200, PreviewAudio.MaxPreviewMs, 80, 0, Sustain: true));
    private static Task<double> Start(PlaybackPlan plan, string path, CancellationToken token = default) =>
        Task.Factory.StartNew(() => PreviewAudio.WriteWave(plan, path, token), CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
    private static Exception? Capture(Action action)
    {
        try { action(); return null; }
        catch (Exception error) { return error; }
    }
    private static void WriteNew(string path, byte[] bytes)
    {
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        stream.Write(bytes);
    }
    private static string? WaitForFile(Task render, string root, string pattern, long minimumLength, string? ignored = null)
    {
        // Observe actual I/O progress, not a CancelAfter guess. All paths are in this test's UUID root.
        // A timeout/non-observation is a test failure, never an assumed cancellation success.
        var watch = Stopwatch.StartNew();
        while (!render.IsCompleted && watch.Elapsed < TimeSpan.FromMinutes(2))
        {
            foreach (string path in Directory.EnumerateFiles(root, ".qinban-preview-" + pattern))
            {
                if (Path.GetFileName(path) == ignored) continue;
                var info = new FileInfo(path);
                if (info.Exists && info.Length > minimumLength) return path;
            }
            Thread.SpinWait(1000);
        }
        return null;
    }
    private static void Header(byte[] bytes, double duration, Action<bool, string> check)
    {
        int count = (int)Math.Ceiling(duration * PreviewAudio.SampleRate / 1000);
        check(Encoding.ASCII.GetString(bytes, 0, 4) == "RIFF" && Encoding.ASCII.GetString(bytes, 8, 8) == "WAVEfmt " && Encoding.ASCII.GetString(bytes, 36, 4) == "data", "RIFF chunks");
        check(BitConverter.ToInt32(bytes, 4) == bytes.Length - 8 && BitConverter.ToInt32(bytes, 16) == 16, "RIFF / fmt lengths");
        check(BitConverter.ToInt16(bytes, 20) == 1 && BitConverter.ToInt16(bytes, 22) == 1 && BitConverter.ToInt32(bytes, 24) == 22050, "PCM format / channels / rate");
        check(BitConverter.ToInt32(bytes, 28) == 44100 && BitConverter.ToInt16(bytes, 32) == 2 && BitConverter.ToInt16(bytes, 34) == 16, "byte rate / block alignment / bits");
        check(bytes.Length == 44 + count * 2 && BitConverter.ToInt32(bytes, 40) == count * 2, "PCM lengths");
    }
    private static (byte[] Pcm, float Peak) ReferencePcm(PlaybackPlan plan)
    {
        // The original full-array algorithm, used ONLY for short deterministic regression fixtures.
        double duration = Math.Min(plan.DurationMs + 450, PreviewAudio.MaxPreviewMs);
        int length = checked((int)Math.Ceiling(duration * PreviewAudio.SampleRate / 1000));
        var samples = new float[length];
        foreach (var note in plan.Notes.Where(n => n.StartMs < duration))
        {
            int start = (int)(note.StartMs * PreviewAudio.SampleRate / 1000);
            int count = Math.Min((int)((note.SoundMs + 120) * PreviewAudio.SampleRate / 1000), length - start);
            var pitches = note.ChordPitches ?? new[] { note.Pitch };
            var frequencies = pitches.Select(pitch => 440 * Math.Pow(2, (pitch - 69) / 12.0)).ToArray();
            double amplitude = .17 * note.Velocity / 127 / Math.Sqrt(pitches.Count);
            double seconds = note.SoundMs / 1000;
            for (int i = 0; i < count; i++)
            {
                double time = (double)i / PreviewAudio.SampleRate;
                double attack = Math.Min(1, time / .005);
                double release = time <= seconds ? 1 : Math.Max(0, 1 - (time - seconds) / .12);
                double envelope = attack * release * (note.Sustain ? .85 : Math.Exp(-time * 2.5 / Math.Max(.08, seconds)));
                double sample = 0;
                foreach (double frequency in frequencies)
                {
                    double phase = 2 * Math.PI * frequency * time;
                    sample += Math.Sin(phase) + .25 * Math.Sin(phase * 2) + .1 * Math.Sin(phase * 3);
                }
                samples[start + i] += (float)(amplitude * envelope * sample);
            }
        }
        float peak = samples.Length == 0 ? 1 : samples.Max(x => Math.Abs(x));
        double gain = peak > .94 ? .94 / peak : 1;
        var pcm = new byte[length * sizeof(short)];
        using var output = new BinaryWriter(new MemoryStream(pcm));
        foreach (float value in samples) output.Write((short)Math.Clamp(value * gain * 32767, -32767, 32767));
        return (pcm, peak);
    }
}