using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static partial class Program
{
    static int assertions;
    static readonly JsonSerializerOptions Json = new(JsonDefaults.Options) { WriteIndented = true };
    static readonly List<object> WaveEvidence = [];
    static void Require(bool condition, string message) { assertions++; if (!condition) throw new InvalidOperationException(message); }
    static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Json);
    static void WriteNew(string path, string text)
    {
        using var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        using var writer = new StreamWriter(file, new UTF8Encoding(false)); writer.Write(text);
    }
    static string ToolRoot => Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../.."));
    static int Main(string[] args)
    {
        try
        {
            if (args.Length == 1 && args[0] == "--self-test") { SelfTest(); Console.WriteLine($"PASS self-test: {assertions} assertions"); return 0; }
            if (args.Length == 3 && args[0] == "--focused-alltracks") return FocusedAllTracks(args[1], args[2]);
            if (args.Length == 3 && args[0] == "--key-onset-changes") return KeyOnsetChanges(args[1], args[2]);
            if (args.Length is < 2 or > 3) throw new ArgumentException("<repo> <NEW mapping-results.json> [--waves]");
            string repo = Path.GetFullPath(args[0]), output = Path.GetFullPath(args[1]);
            string allowed = Path.Combine(repo, ".validation", "pop100-gap-diagnosis-2026-10-06");
            Require(Path.GetDirectoryName(output) == allowed && Path.GetFileName(output).StartsWith("mapping-", StringComparison.Ordinal), "Output outside authorized mapping-* files");
            Require(!File.Exists(output), "Refusing to overwrite evidence");
            Directory.CreateDirectory(allowed);
            var watch = Stopwatch.StartNew(); string songs = Path.Combine(repo, "Songs"), catalog = Path.Combine(songs, "catalog.db");
            string catalogHash = LibraryCatalog.HashFile(catalog);
            var entries = new List<LibraryEntry>();
            // Mode=ReadOnly, no LibraryStore constructor, migrations, user-directory discovery or persistence.
            using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder {
                DataSource = catalog, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()))
            {
                connection.Open(); using var command = connection.CreateCommand();
                command.CommandText = "SELECT metadata_json FROM entries WHERE relative_path LIKE 'pop909-%' ORDER BY relative_path";
                using var reader = command.ExecuteReader();
                while (reader.Read()) entries.Add(JsonSerializer.Deserialize<LibraryEntry>(reader.GetString(0), JsonDefaults.Options)!);
            }
            Require(entries.Count == 100 && entries.Select(e => e.RelativePath).Distinct().Count() == 100, "Expected exactly 100 distinct POP909 resources");
            var instruments = InstrumentCatalog.All.Where(i => i.CanAutoPlay).ToList();
            var drums = InstrumentCatalog.All.Where(i => !i.CanAutoPlay).ToList();
            Require(instruments.Count == 9 && drums.Count == 3, "Expected 9 melody instruments and 3 disabled drums");
            var matrix = new List<MatrixRow>(); var drumRows = new List<object>(); var sourceEvidence = new List<object>();
            foreach (var entry in entries)
            {
                string id = Path.GetFileNameWithoutExtension(entry.RelativePath).Replace("pop909-", "");
                Require(entry.RelativePath == $"pop909-{id}.json" && id.Length == 3 && id.All(char.IsAsciiDigit), "Unexpected catalog path");
                string path = Path.Combine(songs, entry.RelativePath); string hash = LibraryCatalog.HashFile(path);
                Require(hash.Equals(entry.ResourceHash, StringComparison.OrdinalIgnoreCase), "Resource hash differs from actual catalog: " + id);
                var song = SongParser.Read(path); var originalNotes = song.Notes.ToArray(); string originalSong = Serialize(song), savedOptions = Serialize(entry.Options);
                Require(entry.Options.Tracks != null && entry.Options.Tracks.SequenceEqual(new[] { 1 }), "Catalog original is not Tracks=[1]: " + id);
                Require(entry.Options.Chords == ChordMode.Simultaneous, "Probe requires actual simultaneous catalog chords: " + id);
                var raw1 = song.Notes.Where(n => n.Track == 1 && !n.Percussion).ToList();
                var raw2 = song.Notes.Where(n => n.Track == 2 && !n.Percussion).ToList();
                Require(raw1.Count > 0 && raw2.Count > 0, "Missing track1/track2 source notes: " + id);
                double speed = entry.Options.Speed, duration = song.DurationMs / speed;
                var spans1 = Metrics.Spans(raw1, speed); var spans2 = Metrics.Spans(raw2, speed);
                var rawSound1 = Metrics.Sound(spans1, duration); var rawSound12 = Metrics.Sound(spans1.Concat(spans2), duration);
                var rawOnset1 = Metrics.Onsets(raw1.Select(n => n.StartMs / speed));
                var rawOnset12 = Metrics.Onsets(raw1.Concat(raw2).Select(n => n.StartMs / speed));
                var overlap = Metrics.GetOverlap(spans1, spans2, raw2.Select(n => n.StartMs / speed));
                foreach (var instrument in instruments)
                {
                    var one = entry.Options.Copy(); one.InstrumentId = instrument.Id;
                    var two = one.Copy(); two.Tracks = [1, 2];
                    CheckOptions(entry.Options, one, [1]); CheckOptions(entry.Options, two, [1, 2]);
                    var a = GameMapping.Build(song, one); var b = GameMapping.Build(song, two);
                    int shortened1 = ValidatePlan(song, one, a), shortened2 = ValidatePlan(song, two, b);
                    Require(Metrics.Near(a.DurationMs, b.DurationMs), $"Changed total timeline: {id}/{instrument.Id}");
                    Require(originalNotes.SequenceEqual(song.Notes) && originalSong == Serialize(song), "Source notes/document mutated");
                    CheckOptions(entry.Options, one, [1]); CheckOptions(entry.Options, two, [1, 2]);
                    var statsA = Metrics.Plan(a, shortened1); var statsB = Metrics.Plan(b, shortened2);
                    var gapFill = statsA.Sound.GapsGe5s.Select(g => new GapFill(g.StartMs, g.EndMs, g.DurationMs,
                        Metrics.Intersect([g], spans2), Metrics.Intersect([g], Metrics.Spans(b.Notes)),
                        g.DurationMs - Metrics.Intersect([g], Metrics.Spans(b.Notes)))).ToList();
                    matrix.Add(new(id, song.Title, instrument.Id, one, two, raw1.Count, raw2.Count,
                        song.Notes.Count - raw1.Count - raw2.Count, rawSound1, rawSound12, rawOnset1, rawOnset12, overlap,
                        statsA, statsB, Metrics.Delta(a, b), gapFill, true));
                    if (args.Length == 3 && args[2] == "--waves" && id is "035" or "038" && instrument.Id is "windsong" or "harmonic")
                        RenderPair(id, instrument.Id, a, b, allowed);
                }
                foreach (var drum in drums)
                {
                    foreach (var tracks in new List<int>[] { [1], [1, 2] })
                    {
                        var opts = entry.Options.Copy(); opts.InstrumentId = drum.Id; opts.Tracks = tracks;
                        var plan = GameMapping.Build(song, opts);
                        Require(plan.Notes.Count == 0 && plan.Report.Output == 0 && plan.DurationMs == 0, "Drum unexpectedly generated output");
                        Require(originalNotes.SequenceEqual(song.Notes), "Drum mapping mutated source");
                        drumRows.Add(new { id, instrument = drum.Id, tracks, output = plan.Notes.Count, passed = true });
                    }
                }
                Require(hash == LibraryCatalog.HashFile(path), "Source file bytes changed: " + id);
                Require(savedOptions == Serialize(entry.Options), "Catalog options changed in memory: " + id);
                sourceEvidence.Add(new { id, path, sha256 = hash, notes = song.Notes.Count, sourceTracks = song.Tracks,
                    catalogOptions = entry.Options, unchangedInMemory = true, unchangedOnDisk = true });
                Console.WriteLine($"PASS {id} {song.Title}: 9 melody pairs + 6 disabled-drum plans");
            }
            Require(matrix.Count == 900 && drumRows.Count == 600, "Incomplete matrix");
            Require(catalogHash == LibraryCatalog.HashFile(catalog), "Catalog bytes changed");
            var summary = new {
                songs = entries.Count, melodyInstruments = instruments.Select(i => i.Id), matrixRows = matrix.Count,
                melodyPlans = matrix.Count * 2, disabledDrumRows = drumRows.Count, actualGameMappingBuildCalls = matrix.Count * 2 + drumRows.Count,
                passedMatrixRows = matrix.Count(r => r.Passed), assertions,
                soundInternalGe5sOriginal = matrix.Sum(r => r.Original.Sound.CountGe5s), soundInternalGe5sCandidate = matrix.Sum(r => r.Candidate.Sound.CountGe5s),
                soundInternalGe5sOriginalMs = matrix.Sum(r => r.Original.Sound.TotalGe5sMs), soundInternalGe5sCandidateMs = matrix.Sum(r => r.Candidate.Sound.TotalGe5sMs),
                rowsWithSoundGe5sOriginal = matrix.Count(r => r.Original.Sound.CountGe5s > 0), rowsWithSoundGe5sCandidate = matrix.Count(r => r.Candidate.Sound.CountGe5s > 0),
                onsetGe5sOriginal = matrix.Sum(r => r.Original.Onsets.CountGe5s), onsetGe5sCandidate = matrix.Sum(r => r.Candidate.Onsets.CountGe5s),
                onsetGe5sOriginalMs = matrix.Sum(r => r.Original.Onsets.TotalGe5sMs), onsetGe5sCandidateMs = matrix.Sum(r => r.Candidate.Onsets.TotalGe5sMs),
                soundLongGapCountImprovedRows = matrix.Count(r => r.Candidate.Sound.CountGe5s < r.Original.Sound.CountGe5s),
                soundLongGapCountEqualRows = matrix.Count(r => r.Candidate.Sound.CountGe5s == r.Original.Sound.CountGe5s),
                soundLongGapCountWorseRows = matrix.Count(r => r.Candidate.Sound.CountGe5s > r.Original.Sound.CountGe5s),
                maxCandidateExactOnsetKeys = matrix.Max(r => r.Candidate.Density.MaxExactOnsetKeys),
                maxCandidateExactOnsetVoices = matrix.Max(r => r.Candidate.Density.MaxExactOnsetVoices),
                maxCandidateConcurrentKeys = matrix.Max(r => r.Candidate.Density.MaxConcurrentKeys),
                maxCandidateConcurrentVoices = matrix.Max(r => r.Candidate.Density.MaxConcurrentVoices),
                removedOriginalKeyOnsets = matrix.Sum(r => r.Delta.RemovedKeyOnsets),
                removedOriginalDistinctTimes = matrix.Sum(r => r.Delta.RemovedDistinctTimes), changedCommonKeyOnsets = matrix.Sum(r => r.Delta.ChangedCommonKeyOnsets)
            };
            WriteNew(output, Serialize(new {
                status = "PASS_READ_ONLY_MAPPING_MATRIX__NOT_PRODUCTION_CHANGED__NOT_GAME_OR_MUSIC_VALIDATED",
                generatedAt = DateTimeOffset.Now, repo, catalog, catalogSha256 = catalogHash,
                coreAssemblyPath = typeof(GameMapping).Assembly.Location,
                coreAssemblySha256 = LibraryCatalog.HashFile(typeof(GameMapping).Assembly.Location),
                mapperSourceSha256 = LibraryCatalog.HashFile(Path.Combine(repo, "QinBan.Core", "GameMapping.cs")),
                elapsedMs = watch.ElapsedMilliseconds, summary, sourceEvidence, matrix, disabledDrums = drumRows, waveEvidence = WaveEvidence,
                boundaries = new[] { "GameMapping.Build direct; no mapper pitch-selection implementation copied", "No PlaybackEngine/OS input/audio playback/UserData access",
                    "SoundMs union is planned sounding occupancy, not measured waveform envelope/game sound", "Internal gaps only; leading/trailing separately",
                    "Source notes unchanged is NOT original mapped-note retention; dedup/chord limits/native chords/sustain release may replace output",
                    "Options differ only in instrument for cross-instrument matrix and Tracks for candidate; actual per-song transpose/speed preserved" }
            }));
            Console.WriteLine(Serialize(summary)); return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
    static void CheckOptions(PlayOptions catalog, PlayOptions actual, List<int> tracks)
    {
        Require(actual.Speed == catalog.Speed && actual.Transpose == catalog.Transpose && actual.Octave == catalog.Octave, "Speed/transpose/octave changed");
        Require(actual.Tracks != null && actual.Tracks.SequenceEqual(tracks), "Track selection unexpected");
        var normalized = actual.Copy(); normalized.InstrumentId = catalog.InstrumentId; normalized.Tracks = catalog.Tracks?.ToList();
        Require(Serialize(normalized) == Serialize(catalog), "Non-authorized Options change");
    }
    static int ValidatePlan(SongDocument song, PlayOptions options, PlaybackPlan plan)
    {
        Require(plan.Notes.Count > 0 && plan.Report.Original == song.Notes.Count && plan.Report.Output == plan.Notes.Count, "Empty or inconsistent output");
        Require(plan.Notes.SequenceEqual(plan.Notes.OrderBy(n => n.StartMs).ThenBy(n => n.Pitch)), "Unsorted output");
        Require(plan.Notes.Select(n => (n.Key, n.StartMs)).Distinct().Count() == plan.Notes.Count, "Duplicate key/onset");
        var instrument = InstrumentCatalog.Get(options.InstrumentId); var keys = instrument.Keys.ToDictionary(k => k.Key);
        var selected = song.Notes.Where(n => options.Tracks!.Contains(n.Track) && (!options.ExcludePercussion || !n.Percussion))
            .GroupBy(n => n.StartMs / options.Speed).ToDictionary(g => g.Key, g => g.ToList());
        // Check timing and source provenance, NOT reimplement pitch folding/nearest-note selection.
        var releaseLimits = new Dictionary<(char Key, double Start), double>();
        foreach (var group in plan.Notes.GroupBy(n => n.Key))
        {
            var ordered = group.OrderBy(n => n.StartMs).ToArray();
            for (int i = 0; i + 1 < ordered.Length; i++)
            {
                double gap = ordered[i + 1].StartMs - ordered[i].StartMs;
                releaseLimits[(ordered[i].Key, ordered[i].StartMs)] = Math.Max(.1, gap - Math.Min(8, gap / 4));
            }
        }
        int shortened = 0;
        foreach (var note in plan.Notes)
        {
            Require(double.IsFinite(note.StartMs) && note.StartMs >= 0 && double.IsFinite(note.SoundMs) && note.SoundMs > 0
                && double.IsFinite(note.HoldMs) && note.HoldMs > 0, "Illegal planned time/duration");
            Require(options.Tracks!.Contains(note.Track), "Output track outside selected source tracks");
            Require(keys.TryGetValue(note.Key, out var key) && key.Pitches[0] == note.Pitch
                && (key.IsChord ? note.ChordPitches != null && note.ChordPitches.SequenceEqual(key.Pitches) : note.ChordPitches == null), "Invalid catalog key/pitch/chord");
            Require(note.Sustain == instrument.SupportsSustain, "Invalid sustain flag");
            Require(selected.TryGetValue(note.StartMs, out var group), "Onset not equal to selected source onset / speed: compressed/shifted/invented");
            var identity = group!.Where(n => n.Track == note.Track && n.Velocity == note.Velocity).ToArray();
            Require(identity.Length > 0, "Output track/velocity not sourced at this onset");
            double[] durations;
            if (key!.IsChord)
            {
                Require(options.NativeGuitarChords && options.Chords == ChordMode.Simultaneous && key.Pitches.Count <= options.MaxChordNotes, "Unauthorized native chord");
                Require(group!.All(n => !n.Percussion), "Percussion manufactured into native chord");
                var classes = group!.Select(n => ((n.Pitch + options.Transpose + options.Octave * 12) % 12 + 12) % 12).Distinct().Order();
                Require(classes.SequenceEqual(key.Pitches.Select(p => p % 12).Distinct().Order()), "Native chord has invented pitch classes");
                durations = [group!.Min(n => n.DurationMs) / options.Speed];
            }
            else durations = identity.Select(n => n.DurationMs / options.Speed).ToArray();
            double limit = releaseLimits.GetValueOrDefault((note.Key, note.StartMs), double.PositiveInfinity);
            Require(durations.Any(d => Metrics.Near(note.SoundMs, note.Sustain ? Math.Min(d, limit) : d)
                && Metrics.Near(note.HoldMs, Math.Min(note.Sustain && options.HoldByScore ? d : options.HoldMs, limit))), "Source duration or same-key release contract violated");
            // Count sustain release clipping only, not different-duration same-onset identities or native-chord minimum length.
            if (note.Sustain && Metrics.Near(note.SoundMs, limit) && durations.Any(d => d > limit + Metrics.Epsilon)) shortened++;
        }
        Require(Metrics.Near(plan.DurationMs, Math.Max(song.DurationMs / options.Speed, plan.Notes.Max(n => n.StartMs + n.HoldMs))), "Timeline/terminal rest shortened");
        Require(plan.Report.NativeChords == plan.Notes.Count(n => n.ChordPitches != null), "Native chord count inconsistent");
        return shortened;
    }
    static void RenderPair(string id, string instrument, PlaybackPlan a, PlaybackPlan b, string outputDir)
    {
        var gap = Metrics.Sound(Metrics.Spans(a.Notes), a.DurationMs).GapsGe5s.OrderByDescending(g => g.DurationMs).FirstOrDefault();
        double center = gap == null ? a.Notes[0].StartMs : (gap.StartMs + gap.EndMs) / 2;
        double start = Math.Max(0, center - 14000), end = Math.Min(a.DurationMs, start + 29550);
        string stage = Path.Combine(ToolRoot, "wave-staging"); Directory.CreateDirectory(stage);
        foreach (var pair in new[] { (Name: "tracks1", Plan: a), (Name: "tracks12", Plan: b) })
        {
            var notes = pair.Plan.Notes.Where(n => n.StartMs < end && n.StartMs + n.SoundMs > start)
                .Select(n => n with { StartMs = Math.Max(0, n.StartMs - start), HoldMs = Math.Max(.1, Math.Min(n.HoldMs, end - Math.Max(n.StartMs, start))),
                    SoundMs = Math.Min(n.StartMs + n.SoundMs, end) - Math.Max(n.StartMs, start) }).ToList();
            Require(notes.Count > 0, "Fragment contains no notes");
            string name = $"mapping-{id}-{instrument}-{pair.Name}-max30s.wav", staged = Path.Combine(stage, name), target = Path.Combine(outputDir, name);
            double returned = PreviewAudio.WriteWave(new(notes, end - start, pair.Plan.Report, ["Synthetic fragment; never played"]), staged);
            byte[] data = File.ReadAllBytes(staged); double actual = (data.Length - 44) / 2.0 / PreviewAudio.SampleRate * 1000;
            Require(Encoding.ASCII.GetString(data, 0, 4) == "RIFF" && Encoding.ASCII.GetString(data, 8, 4) == "WAVE"
                && BitConverter.ToInt32(data, 24) == PreviewAudio.SampleRate && BitConverter.ToInt32(data, 40) == data.Length - 44
                && data.AsSpan(44).ContainsAnyExcept((byte)0), "Invalid/silent WAV");
            Require(actual <= 30000 + 1000.0 / PreviewAudio.SampleRate && Math.Abs(returned - actual) <= 1000.0 / PreviewAudio.SampleRate, "WAV >30 seconds");
            File.Copy(staged, target, false);
            WaveEvidence.Add(new { id, instrument, tracks = pair.Name, path = target, sha256 = LibraryCatalog.HashFile(target),
                sourceStartMs = start, sourceEndMs = end, waveDurationMs = actual, gap, notes = notes.Count,
                carryInClippedAndReattacked = true, played = false, boundary = "Same absolute window; synthetic PCM, boundary-crossing notes clipped/re-attacked; not game/original audio" });
        }
    }
    static void SelfTest()
    {
        var union = Metrics.Union([new(0, 7000), new(1000, 2000), new(6000, 8000), new(13000, 14000)]);
        Require(union.SequenceEqual(new Span[] { new(0, 8000), new(13000, 14000) }), "Union nesting/overlap");
        var sound = Metrics.Sound(union, 15000); Require(sound.CountGe5s == 1 && sound.TotalGe5sMs == 5000 && sound.TrailingMs == 1000, "Exact 5s inclusive/trailing");
        Require(Metrics.Sound([new(0, 10000), new(6000, 7000)], 10000).CountGe5s == 0
            && Metrics.Onsets([0, 6000]).CountGe5s == 1, "Onset gap must not equal sound silence");
        Require(Metrics.Intersect([new(0, 1000), new(500, 1500)], [new(750, 2000)]) == 750, "Overlap must union before intersection");
        var song = new SongDocument { Title = "Probe fixture", LengthMs = 30000, Notes = [new(60, 1000, 1000, 1),
            new(62, 10000, 1000, 1), new(64, 5000, 2000, 2), new(67, 7000, 1000, 3)] };
        string before = Serialize(song); var one = new PlayOptions { Tracks = [1], Speed = 2, Transpose = 2 };
        var two = one.Copy(); two.Tracks = [1, 2]; var a = GameMapping.Build(song, one); var b = GameMapping.Build(song, two);
        ValidatePlan(song, one, a); ValidatePlan(song, two, b);
        Require(b.Notes.All(n => n.Track is 1 or 2) && b.Notes.Any(n => n.StartMs == 2500 && n.Track == 2), "Tracks/timeline fixture");
        Require(before == Serialize(song) && a.DurationMs == 15000 && b.DurationMs == 15000, "Source/terminal rest preserved");
        var invalid = b with { Notes = b.Notes.Select(n => n with { StartMs = n.StartMs - 1 }).ToList() };
        bool caught = false; try { ValidatePlan(song, two, invalid); } catch (InvalidOperationException) { caught = true; }
        Require(caught, "Provenance assertion must reject compressed timing");
        var chordSong = new SongDocument { Title = "Chord fixture", Notes = [new(60, 1000, 900, 1), new(64, 1000, 700, 2), new(67, 1000, 800, 2)] };
        var opts = new PlayOptions { InstrumentId = "ukulele", Tracks = [1, 2] };
        var chord = GameMapping.Build(chordSong, opts); ValidatePlan(chordSong, opts, chord);
        Require(chord.Report.NativeChords == 1 && chord.Notes[0].SoundMs == 700, "Exact native chord/source minimum duration");
        Require(Metrics.GetDensity(chord.Notes).MaxExactOnsetKeys == 1 && Metrics.GetDensity(chord.Notes).MaxExactOnsetVoices == 3, "Native chord density expansion");
        var unequal = new SongDocument { Title = "Different source durations", Notes = [new(60, 1000, 800, 1), new(64, 1000, 1200, 1)] };
        var nonSustain = new PlayOptions { Tracks = [1] };
        Require(ValidatePlan(unequal, nonSustain, GameMapping.Build(unequal, nonSustain)) == 0, "Non-sustain duration identities are not sustain clipping");
        var repeated = new SongDocument { Title = "Actual sustain clipping", Notes = [new(60, 1000, 5000, 1), new(60, 2000, 1000, 1)] };
        var sustainOptions = new PlayOptions { InstrumentId = "harmonic", Tracks = [1] };
        Require(ValidatePlan(repeated, sustainOptions, GameMapping.Build(repeated, sustainOptions)) == 1, "Actual same-key sustain clipping must be counted");
        Require(ValidatePlan(chordSong, new PlayOptions { InstrumentId = "ukulele", Tracks = [1, 2] }, chord) == 0, "Native minimum duration is not sustain clipping");
        foreach (var drum in InstrumentCatalog.All.Where(i => !i.CanAutoPlay))
        { opts.InstrumentId = drum.Id; Require(GameMapping.Build(chordSong, opts).Notes.Count == 0, "Disabled drum fixture"); }
    }
}




