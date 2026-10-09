using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Melanchall.DryWetMidi.Core;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static class BuildRunner
{
    public const string LicenseDeclaration = "POP909 repository MIT; underlying song redistribution unverified";
    public static BuildReport Build(string manifestPath, string baseline, string output, bool syntheticFixture)
    {
        manifestPath = Path.GetFullPath(manifestPath); baseline = Path.GetFullPath(baseline); output = Path.GetFullPath(output);
        Files.NoLinks(manifestPath); Files.NoLinks(baseline); Files.NoLinks(output);
        Files.Require(!File.Exists(output) && !Directory.Exists(output), "输出已存在，拒绝覆盖: " + output);
        Files.Require(!Files.Within(output, baseline) && !Files.Within(baseline, output)
            && !Files.Within(manifestPath, output), "输入输出目录不得重叠");
        Files.Require(Directory.Exists(baseline), "基线目录不存在");
        var manifest = Files.Read<Manifest>(manifestPath);
        ValidateManifest(manifest, syntheticFixture, output);
        string manifestHash = Files.Hash(manifestPath);
        var baselineBefore = Files.Snapshot(baseline);
        var entries = ReadBaseline(baseline, out var baselineMetadata);
        var referenceHashes = manifest.Songs.ToDictionary(s => s.Id, s => Files.Hash(s.ReferencePath));
        Files.Require(!baselineBefore.Any(f => f.RelativePath.EndsWith("-wal", StringComparison.OrdinalIgnoreCase)
            || f.RelativePath.EndsWith("-shm", StringComparison.OrdinalIgnoreCase) || f.RelativePath.EndsWith("-journal", StringComparison.OrdinalIgnoreCase)),
            "拒绝有SQLite sidecar的非静态基线，请由主线提供稳定只读目录");
        // Atomically claim the directory with an exclusive marker; even concurrent builds must not share it.
        Directory.CreateDirectory(output);
        using var ownership = new FileStream(Path.Combine(output, ".pop100-output-owner"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
        var report = new BuildReport { SyntheticFixture = syntheticFixture, SourceCommit = manifest.SourceCommit, RetrievedAtUtc = manifest.RetrievedAtUtc };
        try
        {
            string songs = Path.Combine(output, "Songs"), plans = Path.Combine(output, "sample-plans");
            Directory.CreateDirectory(songs); Directory.CreateDirectory(plans); Directory.CreateDirectory(Path.Combine(output, "wav"));
            Files.JsonNew(Path.Combine(output, "input-manifest.json"), manifest);
            Files.JsonNew(Path.Combine(output, "baseline-input-hashes.json"), baselineBefore);
            Files.JsonNew(Path.Combine(output, "baseline-entries.json"), entries);
            foreach (var item in baselineBefore)
            {
                if (item.RelativePath.Equals(LibraryCatalog.FileName, StringComparison.OrdinalIgnoreCase)) continue;
                string target = LibraryCatalog.Resolve(songs, item.RelativePath);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(LibraryCatalog.Resolve(baseline, item.RelativePath), target, overwrite: false);
                Files.Require(Files.Hash(target) == item.Sha256, "基线复制SHA不同: " + item.RelativePath);
            }
            var shuffled = manifest.Songs.Select(s => s.Id).Order(StringComparer.Ordinal).ToList();
            var random = new Random(report.Seed);
            for (int i = shuffled.Count - 1; i > 0; i--) { int j = random.Next(i + 1); (shuffled[i], shuffled[j]) = (shuffled[j], shuffled[i]); }
            report.SampleIds = shuffled.Take(5).ToList(); var samples = report.SampleIds.ToHashSet();
            var melodic = InstrumentCatalog.All.Where(i => i.CanAutoPlay).ToList();
            var drums = InstrumentCatalog.All.Where(i => !i.CanAutoPlay).ToList();
            Files.Require(melodic.Count == 9 && drums.Count == 3, "Core乐器配置与预期9+3不符");
            foreach (var input in manifest.Songs.OrderBy(s => s.Id, StringComparer.Ordinal))
            {
                Console.WriteLine("CONVERT " + input.Id + " " + input.Title);
                Files.Require(Files.Hash(input.MidiPath).Equals(input.SourceSha256, StringComparison.OrdinalIgnoreCase), "MIDI SHA不符: " + input.Id);
                var song = SongParser.Read(input.MidiPath);
                string nativeNotes = Files.Json(song.Notes); double length = song.LengthMs, bpm = song.Bpm;
                var trackInfo = ReadTracks(input.MidiPath, song);
                var selected = trackInfo.Where(t => t.SourceNames.Any(n => n.Trim().Equals("MELODY", StringComparison.OrdinalIgnoreCase))
                    && song.Notes.Any(n => n.Track == t.Id && !n.Percussion)).Select(t => t.Id).ToList();
                var warnings = new List<string>(song.Warnings);
                if (selected.Count == 0)
                {
                    // Never fall back to all tracks or infer BRIDGE as the melody.
                    var single = trackInfo.Where(t => song.Notes.Any(n => n.Track == t.Id && !n.Percussion)).ToList();
                    Files.Require(single.Count == 1, "缺少可用MELODY，且多轨无法安全猜测；拒绝默认全部伴奏: " + input.Id);
                    selected = [single[0].Id]; warnings.Add("未发现MELODY，仅存在一条有旋律音符的轨道，默认选择该唯一轨；待人工确认。");
                }
                if (selected.Count > 1) warnings.Add("发现多条MELODY，默认均选中；请人工复核旋律叠加。");
                if (song.Notes.Any(n => n.Percussion)) warnings.Add("保留打击乐音符，默认映射排除打击乐。");
                song.Title = input.Title; song.Author = "POP909钢琴编配（编配者未逐首标注）";
                song.Category = "POP909 · 待音乐审核";
                song.Source = "POP909 MIDI / " + input.Id + " / commit " + manifest.SourceCommit;
                song.Description = "保留原MIDI全部音符、轨道与完整tempo map转换后的毫秒时序；默认只选MELODY，其他轨可手动勾选。"
                    + "tempo事件本身不能由Core原生notes JSON表示；参考文件中的tempoChanges仅作来源证据，不把该JSON导出MIDI当作原tempo曲线。";
                song.Provenance = new() {
                    WorkId = "pop909:" + input.Id, EditionId = "pop909:" + manifest.SourceCommit + ":" + input.Id,
                    Artist = input.Artist, Artists = [input.Artist], LanguageTags = [.. input.LanguageTags], Provider = "POP909",
                    SourceUrl = input.SourceUrl, SourceSha256 = input.SourceSha256, RetrievedAt = manifest.RetrievedAtUtc,
                    License = LicenseDeclaration, Completeness = "unknown", TimingStatus = "unverified",
                    MusicReview = "not-reviewed", GameReview = "not-tested", RedistributionVerified = false, Synthetic = syntheticFixture
                };
                song.Warnings = warnings.Distinct().ToList();
                string fileName = "pop909-" + input.Id + ".json", targetScore = Path.Combine(songs, fileName);
                Files.Require(!File.Exists(targetScore), "与基线资源冲突: " + fileName);
                // Compare in memory before stamping, then again against the actual serialized native score.
                PlanChecks.CompareReference(song, input.ReferencePath, input.SourceSha256);
                song.Provenance.TimingStatus = "source-compared";
                Files.TextNew(targetScore, SongParser.ToJson(song));
                var normalized = SongParser.Read(targetScore);
                Files.Require(nativeNotes == Files.Json(normalized.Notes) && length == normalized.LengthMs && bpm == normalized.Bpm
                    && Files.Json(song) == Files.Json(normalized), "原谱notes/轨道/时序/元数据JSON往返变化: " + input.Id);
                var comparison = PlanChecks.CompareReference(normalized, input.ReferencePath, input.SourceSha256);
                Files.Require(comparison.ReferenceSha256 == referenceHashes[input.Id], "reference在转换期间变化");
                string hash = Files.Hash(targetScore);
                int defaultTranspose = ChooseStandardTranspose(song, selected);
                var entry = LibraryStore.Create(normalized, fileName, input.SourceSha256, builtin: true);
                entry.Id = entry.CatalogId = "builtin:" + fileName; entry.ResourceHash = hash;
                entry.AddedAt = manifest.RetrievedAtUtc; entry.Options = Defaults("windsong", selected, defaultTranspose); entries.Add(entry);
                report.Songs.Add(new(input.Id, input.Title, input.Artist, input.LanguageTags, input.SourceUrl,
                    input.SourceSha256, hash, song.Notes.Count, song.LengthMs, song.DurationMs, song.Bpm,
                    trackInfo.Select(t => t with { Selected = selected.Contains(t.Id) }).ToList(), selected, comparison, warnings));
                bool sampled = samples.Contains(input.Id);
                foreach (var instrument in melodic)
                {
                    try
                    {
                        var options = Defaults(instrument.Id, selected, defaultTranspose);
                        var plan = GameMapping.Build(song, options);
                        var assessment = PlanChecks.Assess(input.Id, song, instrument, options, plan, sampled);
                        Files.Require(nativeNotes == Files.Json(song.Notes) && song.LengthMs == length && song.Bpm == bpm
                            && Files.Json(song) == Files.Json(normalized), "映射修改源谱: " + input.Id + "/" + instrument.Id);
                        report.Mappings.Add(assessment);
                        if (sampled)
                        {
                            Files.JsonNew(Path.Combine(plans, $"pop909-{input.Id}.{instrument.Id}.plan.json"), new {
                                input.Id, input.Title, input.Artist, input.SourceSha256, options, assessment, plan,
                                sourceNotes = song.Notes, distinctSourceDurations = song.Notes.Select(n => n.DurationMs).Distinct().Order().ToArray(),
                                distinctSoundDurations = plan.Notes.Select(n => n.SoundMs).Distinct().Order().ToArray(),
                                distinctHoldDurations = plan.Notes.Select(n => n.HoldMs).Distinct().Order().ToArray(),
                                lossMeaning = "源减输出含未选伴奏/打击乐、折叠/半音替换、和弦简化/同键合并/原生和弦压缩，不等同丢失旋律。",
                                noTransposeApplied = true, evidenceClass = report.EvidenceClass
                            });
                            if (instrument.Id is "windsong" or "harmonic") report.Waves.Add(PlanChecks.RenderFragment(input.Id, instrument.Id, plan, output));
                        }
                    }
                    catch (Exception ex) { report.Failures.Add(input.Id + "/" + instrument.Id + ": " + ex); }
                }
                // Stronger than just the 5 samples: every input must be blocked on all 3 drum profiles.
                foreach (var drum in drums)
                {
                    var blocked = GameMapping.Build(song, Defaults(drum.Id, selected));
                    bool ok = blocked.Notes.Count == 0 && blocked.DurationMs == 0 && blocked.Warnings.Count > 0
                        && blocked.Warnings.Any(w => w.Contains(drum.Note, StringComparison.Ordinal));
                    report.Drums.Add(new(input.Id, drum.Id, ok, blocked.Warnings));
                    Files.Require(ok && nativeNotes == Files.Json(song.Notes), "鼓类未阻止/修改源谱: " + drum.Id);
                }
            }
            Files.Require(report.Failures.Count == 0 && report.Mappings.Count == manifest.Songs.Count * 9
                && report.Waves.Count == 10 && report.Drums.Count == manifest.Songs.Count * 3, "映射/试听矩阵失败或不全，查看failures");
            Files.JsonNew(Path.Combine(output, "expected-entries.json"), entries);
            string catalog = Path.Combine(songs, LibraryCatalog.FileName);
            Files.Require(!File.Exists(catalog), "拒绝覆盖目录数据库");
            LibraryCatalog.Build(catalog, entries, songs);
            PreserveBaselineMetadata(catalog, baselineMetadata);
            report.BaselineMetadataUnchanged = true;
            string data = Path.Combine(output, "isolated-UserData");
            report.ColdStart = VerifyStore(songs, data, entries);
            // Exercise options persistence before the process restart, never touching real UserData.
            var store = new LibraryStore(data, songs);
            foreach (var e in entries.Where(e => e.Provenance.Provider == "POP909")) store.Save(store.Find(e.Id)!);
            report.Restart = SpawnRestart(songs, data, Path.Combine(output, "expected-entries.json"), output);
            Files.Require(report.ColdStart.CatalogSha256 == report.Restart.CatalogSha256, "建库冷启/重启改变catalog");
            foreach (var input in manifest.Songs)
            {
                Files.Require(Files.Hash(input.MidiPath).Equals(input.SourceSha256, StringComparison.OrdinalIgnoreCase), "源MIDI变化: " + input.Id);
                Files.Require(Files.Hash(input.ReferencePath) == referenceHashes[input.Id], "源reference变化: " + input.Id);
            }
            Files.Require(Files.Hash(manifestPath) == manifestHash, "manifest变化");
            Files.SameSnapshot(baseline, baselineBefore);
            report.SourceFilesUnchanged = report.BaselineFilesUnchanged = report.NormalizedRoundTripPreserved = true;
            report.IndependentSourceTimingVerified = report.Songs.All(s => s.Timing.Passed);
            report.Status = syntheticFixture ? "PASS_SYNTHETIC_ONLY" : "PASS_SOURCE_COMPARED_NUMERICAL_ONLY_NOT_MUSIC_OR_GAME_REVIEWED";
        }
        catch (Exception ex) { report.Status = "FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH"; report.Failure = ex.ToString(); throw; }
        finally
        {
            report.CompletedAtUtc = DateTimeOffset.UtcNow;
            Files.JsonNew(Path.Combine(output, "build-report.json"), report);
            Files.TextNew(Path.Combine(output, "EVIDENCE-BOUNDARY.txt"),
                "本目录由Pop100Tool生成。失败/部分完成不得发布，详见build-report.json。\n"
                + "POP909独立时序对照依赖主线提供的reference；音乐未经人工审核，游戏未测试，再分发未核验。\n"
                + LicenseDeclaration + "\n默认只选MELODY，不丢弃其他轨。未知语种不推测。\n"
                + "WAV为最多30秒合成音色片段，工具没有播放声音或发送按键；不是原唱/游戏原音。\n"
                + (syntheticFixture ? "本次全部输入为合成夹具（不是真歌），不算100首真实歌集成。\n" : "主线仍需独立检查输出JSON/SHA/目录并决定发布；本工具不执行发布。\n"));
        }
        return report;
    }
    public static PlayOptions Defaults(string instrument, List<int> tracks, int transpose = 0) => new() {
        InstrumentId = instrument, Transpose = transpose, Tracks = [.. tracks], ExcludePercussion = true, Speed = 1, Octave = 0,
        HoldByScore = true, Chords = ChordMode.Simultaneous, MaxChordNotes = 5, Accidentals = AccidentalMode.Nearest, Range = RangeMode.FoldOctaves
    };
    private static void ValidateManifest(Manifest manifest, bool fixture, string output)
    {
        Files.Require(manifest.Songs != null && (fixture ? manifest.Songs.Count >= 5 && manifest.Songs.Count <= 10 : manifest.Songs.Count == 100), "生产build必须恰好100首；内部小夹具5至10首");
        Files.Require(!string.IsNullOrWhiteSpace(manifest.SourceCommit) && manifest.SourceCommit.Length <= 256, "sourceCommit缺失/过长");
        Files.Require(manifest.RetrievedAtUtc != default && manifest.RetrievedAtUtc.Offset == TimeSpan.Zero, "retrievedAtUtc必须显式UTC");
        Files.Require(manifest.Songs!.All(s => s != null) && manifest.Songs.Select(s => s.Id).Distinct().Count() == manifest.Songs.Count, "manifest空条目/重复ID");
        foreach (var s in manifest.Songs)
        {
            Files.Require(s.Id != null && Regex.IsMatch(s.Id, "^[0-9]{3}$") && int.Parse(s.Id) is >= 1 and <= 909, "POP909 ID须为001至909");
            Files.Require(!string.IsNullOrWhiteSpace(s.Title) && !string.IsNullOrWhiteSpace(s.Artist), "真实标题/歌手不可缺失: " + s.Id);
            Files.Require(!string.IsNullOrWhiteSpace(s.SourceUrl) && Uri.TryCreate(s.SourceUrl, UriKind.Absolute, out var uri)
                && uri.Scheme is "https" or "http", "sourceUrl须为明确HTTP来源");
            Files.Require(s.SourceSha256 != null && Regex.IsMatch(s.SourceSha256, "^[A-Fa-f0-9]{64}$"), "sourceSha256须为64位hex");
            foreach (string path in new[] { s.MidiPath, s.ReferencePath })
            {
                Files.Require(!string.IsNullOrWhiteSpace(path) && Path.IsPathFullyQualified(path) && File.Exists(path), "MIDI/reference须为存在的绝对路径");
                Files.NoLinks(path); Files.Require(!Files.Within(path, output), "输入不可位于输出内");
            }
            Files.Require(Path.GetExtension(s.MidiPath).ToLowerInvariant() is ".mid" or ".midi", "只读原MIDI，不接受flatten JSON");
            new ScoreProvenance { Artist = s.Artist, Artists = [s.Artist], LanguageTags = s.LanguageTags }.Validate();
            Files.Require(Files.Hash(s.MidiPath).Equals(s.SourceSha256, StringComparison.OrdinalIgnoreCase), "源SHA不符: " + s.Id);
        }
    }
    internal static int ChooseStandardTranspose(SongDocument song, List<int> selected)
    {
        var classes = InstrumentCatalog.Get("windsong").Keys.Where(k => !k.IsChord).Select(k => k.Pitches[0] % 12).ToHashSet();
        var notes = song.Notes.Where(n => selected.Contains(n.Track) && !n.Percussion).ToList();
        // One uniform shift preserves intervals. Prefer fewer weighted chromatic substitutions,
        // then fewer affected notes and the smallest shift. Original notes are never rewritten.
        return Enumerable.Range(-6, 13).Select(t => new { Shift = t,
            Weight = notes.Where(n => !classes.Contains(((n.Pitch + t) % 12 + 12) % 12)).Sum(n => n.DurationMs),
            Count = notes.Count(n => !classes.Contains(((n.Pitch + t) % 12 + 12) % 12)) })
            .OrderBy(x => x.Weight).ThenBy(x => x.Count).ThenBy(x => Math.Abs(x.Shift)).ThenBy(x => x.Shift).First().Shift;
    }
    private static List<LibraryEntry> ReadBaseline(string root, out Dictionary<string, string> metadata)
    {
        metadata = new(StringComparer.Ordinal);
        string catalog = Path.Combine(root, LibraryCatalog.FileName); Files.Require(File.Exists(catalog), "必须提供已有32谱catalog.db，不可用fallback猜ID");
        using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = catalog, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()); c.Open();
        using var command = c.CreateCommand(); command.CommandText = "SELECT id,metadata_json FROM entries ORDER BY id";
        using var reader = command.ExecuteReader(); var result = new List<LibraryEntry>();
        while (reader.Read())
        {
            var e = JsonSerializer.Deserialize<LibraryEntry>(reader.GetString(1), JsonDefaults.Options) ?? throw new FormatException("baseline metadata null");
            e.Options.Validate(); e.Provenance.Validate();
            metadata.Add(e.Id, reader.GetString(1));
            Files.Require(e.BuiltIn && e.Id == reader.GetString(0) && e.CatalogId == e.Id, "基线稳定ID/catID不一致");
            string resource = LibraryCatalog.Resolve(root, e.RelativePath); Files.NoLinks(resource);
            Files.Require(Files.Hash(resource).Equals(e.ResourceHash.Length > 0 ? e.ResourceHash : e.Hash, StringComparison.OrdinalIgnoreCase), "baseline SHA不符: " + e.Id);
            if (e.RelativePath.Equals("01.json", StringComparison.OrdinalIgnoreCase)) Files.Require(e.Id == "builtin:01.json", "教学01稳定ID损坏");
            result.Add(e);
        }
        Files.Require(result.Count == 32 && result.Select(e => e.RelativePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 32
            && result.Any(e => e.Id == "builtin:01.json"), "基线须恰好32谱/32独立资源并保留builtin:01.json");
        return result;
    }
    private static void PreserveBaselineMetadata(string catalog, Dictionary<string, string> metadata)
    {
        // Build serializes typed entries; restore exact source JSON, including unknown/missing legacy fields.
        // Only the NEW catalogue is opened read-write. The baseline is never opened through LibraryStore.
        using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = catalog, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString()); c.Open();
        using var tx = c.BeginTransaction();
        foreach (var (id, raw) in metadata)
        {
            using var update = c.CreateCommand(); update.Transaction = tx;
            update.CommandText = "UPDATE entries SET metadata_json=$json WHERE id=$id";
            update.Parameters.AddWithValue("$json", raw); update.Parameters.AddWithValue("$id", id);
            Files.Require(update.ExecuteNonQuery() == 1, "基线元数据恢复缺失ID: " + id);
        }
        tx.Commit();
        foreach (var (id, raw) in metadata)
        {
            using var read = c.CreateCommand(); read.CommandText = "SELECT metadata_json FROM entries WHERE id=$id"; read.Parameters.AddWithValue("$id", id);
            Files.Require(read.ExecuteScalar() as string == raw, "基线metadata JSON变化: " + id);
        }
    }
    private static List<TrackEvidence> ReadTracks(string path, SongDocument song)
    {
        var midi = MidiFile.Read(path, new ReadingSettings { TextEncoding = Encoding.UTF8, EndOfTrackStoringPolicy = EndOfTrackStoringPolicy.Store });
        return midi.GetTrackChunks().Select((t, index) => new TrackEvidence(index,
            t.Events.OfType<SequenceTrackNameEvent>().Select(e => e.Text).Distinct().ToList(), song.Notes.Count(n => n.Track == index), false)).ToList();
    }
    public static StoreEvidence VerifyStore(string songs, string data, List<LibraryEntry> expected)
    {
        Files.NoLinks(songs); Files.NoLinks(data); var store = new LibraryStore(data, songs);
        Files.Require(store.Count == expected.Count && !store.MigratedLegacy && store.LoadWarnings.Count == 0, "隔离LibraryStore数量/迁移/警告不正确");
        int searches = 0;
        foreach (var e in expected)
        {
            var actual = store.Find(e.Id); Files.Require(actual != null && Files.Json(actual) == Files.Json(e), "稳定ID/元数据/Options未保留: " + e.Id);
            if (e.Provenance.Provider != "POP909") continue;
            foreach (string term in new[] { e.Title, e.Provenance.Artist, e.Title + " " + e.Provenance.Artist })
            {
                // Use WorkId to make common-title/common-artist searches valid without assuming unique artists.
                var page = store.Query(new(Search: term, WorkId: e.Provenance.WorkId)); searches++;
                Files.Require(page.Total == 1 && page.Items.Single().Id == e.Id, "标题/歌手/组合搜索失败: " + e.Id + " / " + term);
            }
            var global = store.Query(new(Search: e.Title + " " + e.Provenance.Artist, Limit: 50)); searches++;
            Files.Require(global.Total > 0, "全库组合搜索为空");
            for (int offset = 0; offset < global.Total; offset += 50)
            {
                var page = store.Query(new(Search: e.Title + " " + e.Provenance.Artist, Offset: offset, Limit: 50)); searches++;
                if (page.Items.Any(x => x.Id == e.Id)) break;
                Files.Require(offset + 50 < global.Total, "全库搜索未找到目标ID");
            }
            Files.Require(!e.Provenance.IsFormalSong && e.Provenance.TimingStatus == "source-compared"
                && e.Provenance.MusicReview == "not-reviewed" && e.Provenance.GameReview == "not-tested"
                && !e.Provenance.RedistributionVerified && e.Provenance.License == LicenseDeclaration
                && e.Options.Tracks is { Count: > 0 }, "POP provenance/default异常");
        }
        Files.Require(store.SongReads == 0, "搜索发生eager parse");
        foreach (var e in expected)
        {
            var song = store.LoadSong(store.Find(e.Id)!);
            var raw = SongParser.Read(LibraryCatalog.Resolve(songs, e.RelativePath));
            Files.Require(song.Notes.Count == e.NotesCount && song.Bpm == e.Bpm && song.DurationMs == e.DurationMs
                && Files.Json(song) == Files.Json(raw), "目录加载与原谱内容不同: " + e.Id);
            // Legacy teaching JSON deliberately has no catalogue-only CC0/source metadata.
            // Catalogue metadata is checked separately above; do not rewrite old scores to satisfy a test.
            if (e.Provenance.Provider == "POP909")
                Files.Require(Files.Json(song.Provenance) == Files.Json(e.Provenance), "新POP规范谱来源与目录不同: " + e.Id);
        }
        var statistics = store.Statistics();
        Files.Require(statistics.Scores == expected.Count && statistics.UserScores == 0
            && statistics.FormalSongs == expected.Count(e => e.Provenance.IsFormalSong), "隔离统计错误/误增加正式歌");
        return new(Environment.ProcessId, store.Count, searches, store.SongReads, statistics,
            Files.Hash(Path.Combine(songs, LibraryCatalog.FileName)), true, true);
    }
    private static StoreEvidence SpawnRestart(string songs, string data, string expected, string output)
    {
        string process = Environment.ProcessPath ?? throw new InvalidOperationException("process path absent");
        var info = new ProcessStartInfo(process) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = ToolLocation.Root };
        if (Path.GetFileNameWithoutExtension(process).Equals("dotnet", StringComparison.OrdinalIgnoreCase)) info.ArgumentList.Add(Assembly.GetExecutingAssembly().Location);
        string report = Path.Combine(output, "restart-report.json");
        foreach (string a in new[] { "restart-check", songs, data, expected, report }) info.ArgumentList.Add(a);
        using var child = Process.Start(info) ?? throw new InvalidOperationException("restart start failed");
        var stdout = child.StandardOutput.ReadToEndAsync(); var stderr = child.StandardError.ReadToEndAsync();
        if (!child.WaitForExit(120000)) { child.Kill(entireProcessTree: true); throw new TimeoutException("owned restart helper超时120s"); }
        Task.WaitAll(stdout, stderr);
        Files.TextNew(Path.Combine(output, "restart.stdout.log"), stdout.Result); Files.TextNew(Path.Combine(output, "restart.stderr.log"), stderr.Result);
        Files.Require(child.ExitCode == 0, "restart helper failed: " + stderr.Result);
        var result = Files.Read<StoreEvidence>(report);
        Files.Require(result.ProcessId == child.Id && result.ProcessId != Environment.ProcessId, "不是独立进程restart");
        return result;
    }
}
