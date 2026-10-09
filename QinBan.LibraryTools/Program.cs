using System.Diagnostics;
using System.Text.Json;
using QinBan.Core;

if (args.Length < 1) { Console.Error.WriteLine("catalog <Songs> <catalog.db> <report.json> | benchmark <new-output-dir> | normalize <source.mid> <reference.json> <new-output.json> | verify-timing <local-fixtures> <new-report.json>"); return 2; }
try
{
    switch (args[0])
    {
        case "catalog":
        {
            if (args.Length != 4) throw new ArgumentException("catalog requires source directory, new catalogue path and new report path.");
            string source = Path.GetFullPath(args[1]), target = Path.GetFullPath(args[2]);
            if (File.Exists(target) || File.Exists(args[3])) throw new IOException("Refusing to overwrite an existing catalogue/report. Use a new output path.");
            using var teachingStream = System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("teaching-score-hashes.json")!;
            var known = JsonSerializer.Deserialize<List<TeachingHash>>(teachingStream, JsonDefaults.Options)!;
            var sourceFiles = Directory.GetFiles(source, "*.json").Order(StringComparer.Ordinal).ToArray();
            if (sourceFiles.Length != known.Count || sourceFiles.Any(file => !known.Any(k => k.File == Path.GetFileName(file) && k.Sha256 == LibraryCatalog.HashFile(file))))
                throw new FormatException("This teaching-only builder accepts only the 30 hash-verified project editions. External songs require separate source/rights review; no automatic CC0 attribution.");
            var entries = new List<LibraryEntry>();
            foreach (string file in sourceFiles)
            {
                var song = SongParser.Read(file); string relative = Path.GetFileName(file);
                var entry = LibraryStore.Create(song, relative, LibraryCatalog.HashFile(file), true);
                entry.Id = entry.CatalogId = "builtin:" + relative;
                entry.AddedAt = DateTimeOffset.UnixEpoch.AddMilliseconds(entries.Count);
                // Existing 30 files are explicitly documented CC0 teaching editions, not full commercial songs.
                entry.Provenance = new() { WorkId = "qinban-demo:" + relative, EditionId = entry.Id,
                    Provider = "qinban-demo", License = "CC0-1.0 (project teaching edition)",
                    LicenseUrl = "https://creativecommons.org/publicdomain/zero/1.0/", Completeness = "exercise",
                    Tags = [song.Category, "教学", "练习"], Aliases = [song.Title], SourceSha256 = entry.Hash };
                entries.Add(entry);
            }
            LibraryCatalog.Build(target, entries, source);
            WriteNew(args[3], new { createdAtUtc = DateTimeOffset.UtcNow, scores = entries.Count, fullCommercialSongs = 0,
                sourceFileReadsAtBuild = entries.Count, runtimeLoadMode = "metadata index + selected score only", catalogSha256 = LibraryCatalog.HashFile(target),
                entries = entries.Select(e => new { e.Id, e.Title, e.RelativePath, e.ResourceHash, e.Provenance }) });
            Console.WriteLine($"PASS catalogue: {entries.Count} teaching entries; original scores unchanged; {target}"); break;
        }
        case "benchmark":
        {
            if (args.Length != 2) throw new ArgumentException("benchmark requires a NEW output directory.");
            string output = Path.GetFullPath(args[1]); if (Directory.Exists(output)) throw new IOException("Benchmark output already exists; refusing to overwrite evidence."); Directory.CreateDirectory(output);
            var results = new List<object>();
            foreach (int count in new[] { 20_000, 50_000 }) results.Add(Benchmark(output, count));
            WriteNew(Path.Combine(output, "benchmark-report.json"), new { recordedAtUtc = DateTimeOffset.UtcNow, framework = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                os = System.Runtime.InteropServices.RuntimeInformation.OSDescription, cpuCount = Environment.ProcessorCount,
                processMemoryMiB = Process.GetCurrentProcess().WorkingSet64 / 1048576.0, dataset = "synthetic METADATA ONLY; real songs added = 0", results });
            Console.WriteLine("PASS benchmark written: " + output); break;
        }
        case "normalize":
        {
            if (args.Length is not (4 or 5)) throw new ArgumentException("normalize requires local MIDI, independent reference JSON, NEW normalized JSON and optional NEW timing report.");
            if (args.Length == 5 && File.Exists(args[4])) throw new IOException("Refusing to overwrite timing report.");
            if (File.Exists(args[3])) throw new IOException("Refusing to overwrite output score.");
            var song = SongParser.Read(args[1]); var reference = JsonSerializer.Deserialize<Reference>(File.ReadAllText(args[2]), JsonDefaults.Options) ?? throw new FormatException("Invalid timing reference.");
            double error = VerifyTiming(song, reference);
            song.Provenance.Synthetic = reference.Synthetic;
            song.Provenance.SourceSha256 = LibraryCatalog.HashFile(args[1]); song.Provenance.TimingStatus = "source-compared";
            song.Provenance.MusicReview = "not-reviewed"; song.Provenance.GameReview = "not-tested"; song.Provenance.RedistributionVerified = false;
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[3]))!);
            using (var f = new FileStream(args[3], FileMode.CreateNew)) using (var writer = new StreamWriter(f, new System.Text.UTF8Encoding(false))) writer.Write(SongParser.ToJson(song, false));
            if (args.Length == 5) WriteNew(args[4], new { status = "PASS", recordedAtUtc = DateTimeOffset.UtcNow,
                sourceSha256 = song.Provenance.SourceSha256, normalizedSha256 = LibraryCatalog.HashFile(args[3]),
                referenceSha256 = LibraryCatalog.HashFile(args[2]), notes = song.Notes.Count, maxErrorMs = error,
                checks = "pitch, track, velocity, percussion, onset, duration, total length; no music/rights/game approval" });
            Console.WriteLine($"PASS source timing: {song.Notes.Count} notes; max error {error:0.######}ms. Not human music-reviewed/game-tested/licensed by this check."); break;
        }
        case "verify-timing":
        {
            if (args.Length != 3 || File.Exists(args[2])) throw new ArgumentException("verify-timing requires local fixture directory and NEW report file.");
            var results = new List<object>(); int failures = 0;
            foreach (string referencePath in Directory.GetFiles(args[1], "*.reference.json").Order(StringComparer.Ordinal))
            {
                string source = referencePath[..^".reference.json".Length] + ".mid";
                try
                {
                    var song = SongParser.Read(source);
                    var reference = JsonSerializer.Deserialize<Reference>(File.ReadAllText(referencePath), JsonDefaults.Options) ?? throw new FormatException("Missing reference");
                    double error = VerifyTiming(song, reference);
                    var roundTrip = SongParser.ParseJson(SongParser.ToJson(song,false)); _ = VerifyTiming(roundTrip, reference);
                    results.Add(new { name = Path.GetFileName(source), status = "PASS", notes = song.Notes.Count, maxErrorMs = error, sourceSha256 = LibraryCatalog.HashFile(source) });
                }
                catch (Exception ex) { failures++; results.Add(new { name = Path.GetFileName(source), status = "FAIL", error = ex.Message }); }
            }
            if (results.Count == 0) throw new ArgumentException("No local timing fixtures found.");
            WriteNew(args[2], new { recordedAtUtc = DateTimeOffset.UtcNow, dataset = "self-authored timing fixtures; NOT songs or golden-song samples", actualSongsAdded = 0, cases = results.Count, failures, results });
            Console.WriteLine($"RESULT timing: {results.Count-failures}/{results.Count}; failures {failures}. Not musical-quality evidence.");
            if (failures > 0) return 1; break;
        }
        default: throw new ArgumentException("Unknown command; no changes were made.");
    }
    return 0;
}
catch (Exception ex) { Console.Error.WriteLine("FAIL: " + ex.Message); return 1; }

static double VerifyTiming(SongDocument song, Reference reference)
{
    var a = Sort(song.Notes); var b = Sort(reference.Notes);
    if (a.Count != b.Count) throw new FormatException($"Note count differs: parsed {a.Count}, reference {b.Count}");
    double error = 0;
    for (int i = 0; i < a.Count; i++)
    {
        if (a[i].Pitch != b[i].Pitch || a[i].Track != b[i].Track || a[i].Velocity != b[i].Velocity || a[i].Percussion != b[i].Percussion)
            throw new FormatException("Pitch/voice/velocity mismatch at event " + i);
        error = Math.Max(error, Math.Max(Math.Abs(a[i].StartMs-b[i].StartMs), Math.Abs(a[i].DurationMs-b[i].DurationMs)));
    }
    error = Math.Max(error, Math.Abs(song.DurationMs-reference.LengthMs));
    if (!double.IsFinite(error) || error > .0021) throw new FormatException("Source timing mismatch, maximum ms = " + error);
    return error;
}
static List<NoteEvent> Sort(List<NoteEvent> notes) => notes.OrderBy(n => n.Track).ThenBy(n => Math.Round(n.StartMs, 3)).ThenBy(n => n.Pitch).ThenBy(n => Math.Round(n.DurationMs, 3)).ThenBy(n => n.Velocity).ToList();
static void WriteNew(string path, object value)
{
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
    using var stream = new FileStream(path, FileMode.CreateNew); JsonSerializer.Serialize(stream, value, JsonDefaults.Options);
}
static object Benchmark(string output, int count)
{
    string root = Path.Combine(output, count.ToString()), songs = Path.Combine(root, "Songs"); Directory.CreateDirectory(songs);
    string fixture = Path.Combine(songs, "synthetic-fixture.json");
    File.WriteAllText(fixture, SongParser.ToJson(new SongDocument { Title = "合成压力夹具（不是收录歌曲）", Notes = [new(60, 0, 400), new(64, 800, 200)], Provenance = new() { Synthetic = true } }, false));
    string hash = LibraryCatalog.HashFile(fixture);
    var entries = Enumerable.Range(0,count).Select(i => new LibraryEntry
    {
        Id = "synthetic:" + i.ToString("D6"), CatalogId = "synthetic:" + i.ToString("D6"), BuiltIn = true,
        Title = i == 123 ? "中文搜索测试星光" : "合成压力条目 " + i.ToString("D6"), Author = i % 2 == 0 ? "测试作者甲" : "测试作者乙", Category = "合成压力数据",
        RelativePath = "synthetic-fixture.json", Hash = hash, ResourceHash = hash, DurationMs = 1000 + i % 300 * 1000, NotesCount = 2, Bpm = 60 + i % 100,
        AddedAt = DateTimeOffset.UnixEpoch.AddMilliseconds(i), Provenance = new() { Synthetic = true, WorkId = "synthetic-work:" + i.ToString("D6"), Provider = "benchmark",
            Aliases = ["fixture" + i.ToString("D6")], Tags = [i % 2 == 0 ? "测试流派甲" : "测试流派乙"],
            Artists = ["测试歌手甲", i % 2 == 0 ? "合作歌手乙" : "合作歌手丙"], LanguageTags = i % 2 == 0 ? ["cmn", "en"] : ["yue", "en-US"],
            Album = "测试专辑", VersionLabel = i % 2 == 0 ? "录音室版" : "现场版" }
    }).ToList();
    var watch = Stopwatch.StartNew(); LibraryCatalog.Build(Path.Combine(songs, "catalog.db"), entries, syntheticOnly: true); double buildMs = watch.Elapsed.TotalMilliseconds;
    entries.Clear(); GC.Collect(); GC.WaitForPendingFinalizers();
    watch.Restart(); var store = new LibraryStore(Path.Combine(root, "UserData"), songs); var page = store.Query(new()); double startupMs = watch.Elapsed.TotalMilliseconds;
    if (page.Total != count || page.Items.Count != 50 || store.SongReads != 0) throw new Exception("Metadata lazy/paging benchmark invariant failed.");
    (string Term, int ExpectedMatches)[] terms = [("星光", 1), ("星", 1), ("xingguang", 1), ("zwsscsxg", 1), ("fixture000123", 1),
        ("合成 测试作者甲", count / 2), ("测试歌手甲", count), ("合作歌手乙 cmn", count / 2),
        ("国语 英语 测试专辑 录音室版", count / 2), ("粤语 合作歌手丙 现场版", count / 2), ("999999-not-present", 0)];
    var queries = new List<object>();
    foreach (var (term, expectedMatches) in terms)
    {
        _ = store.Query(new(Search: term)); var times = new List<double>(); int found = 0;
        for (int attempt = 0; attempt < 20; attempt++) { watch.Restart(); var result = store.Query(new(Search: term)); times.Add(watch.Elapsed.TotalMilliseconds); found = result.Total; }
        if (found != expectedMatches) throw new Exception($"Metadata benchmark search mismatch: {term}; expected {expectedMatches}, got {found}.");
        times.Sort(); queries.Add(new { term, matches = found, expectedMatches, medianMs = times[times.Count/2], p95Ms = times[(int)Math.Ceiling(times.Count*.95)-1], maxMs = times[^1] });
    }
    int readsBefore = store.SongReads; watch.Restart(); _ = store.LoadSong(page.Items[0]); double selectedLoadMs = watch.Elapsed.TotalMilliseconds;
    var first = page.Items[0]; first.Favorite = true; watch.Restart(); store.Save(first); double localSaveMs = watch.Elapsed.TotalMilliseconds;
    if (store.SongReads != readsBefore+1 || new LibraryStore(store.DataDirectory,songs).Query(new(Favorites:true)).Total != 1) throw new Exception("Lazy read/local state invariant failed.");
    Console.WriteLine($"MEASURE {count}: open+first page {startupMs:0.##}ms; state save {localSaveMs:0.##}ms; score reads {store.SongReads}");
    return new { count, actualSongsAdded = 0, kind = "synthetic metadata pressure dataset; not musical quality evidence", buildMs, startupMs, firstPageItems = page.Items.Count,
        scoreReadsAtStartup = readsBefore, selectedLoadMs, localSaveMs, catalogBytes = new FileInfo(Path.Combine(songs,"catalog.db")).Length, queries };
}
sealed class Reference { public List<NoteEvent> Notes { get; set; } = []; public double LengthMs { get; set; } public bool Synthetic { get; set; } }
sealed class TeachingHash { public string File { get; set; } = ""; public string Sha256 { get; set; } = ""; }
