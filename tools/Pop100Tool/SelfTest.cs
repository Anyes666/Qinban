using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static class SelfTest
{
    private sealed record FixtureNote(int Track, int Pitch, int Start, int Length, int Velocity, bool Percussion = false);
    public static void Run(string output)
    {
        output = Path.GetFullPath(output); Files.NoLinks(output);
        Files.Require(Files.Within(output, ToolLocation.Root) && !Directory.Exists(output) && !File.Exists(output), "self-test须为工具内全新目录");
        Directory.CreateDirectory(output); string input = Path.Combine(output, "synthetic-input"); Directory.CreateDirectory(input);
        string baseline = Path.Combine(output, "synthetic-baseline-Songs"); Directory.CreateDirectory(baseline);
        var cases = new List<object>(); int failures = 0;
        void Case(string name, Action test)
        {
            try { test(); cases.Add(new { name, status = "PASS" }); Console.WriteLine("PASS " + name); }
            catch (Exception ex) { failures++; cases.Add(new { name, status = "FAIL", error = ex.ToString() }); Console.WriteLine("FAIL " + name + ": " + ex.Message); }
        }
        void Reject(Action test)
        {
            try { test(); } catch (Exception ex) when (ex is InvalidOperationException or FormatException or JsonException or IOException) { return; }
            throw new Exception("应该拒绝但成功");
        }
        var entries = new List<LibraryEntry>();
        for (int i = 1; i <= 32; i++)
        {
            string name = i <= 30 ? $"{i:D2}.json" : $"legacy-synthetic-{i}.json";
            var song = new SongDocument { Title = "合成基线夹具非真歌 " + i, Author = "合成测试作者", LengthMs = 1000,
                Notes = [new(60, 0, 100), new(64, 250, 200)], Provenance = new() { Synthetic = true, Provider = "fixture", WorkId = "synthetic-baseline:" + i } };
            string path = Path.Combine(baseline, name);
            string rawJson = SongParser.ToJson(song);
            // Reproduce real 01.json: provenance is catalogue-only and missing from raw legacy JSON.
            if (i == 1) { var legacy = JsonNode.Parse(rawJson)!.AsObject(); legacy.Remove("provenance"); rawJson = legacy.ToJsonString(JsonDefaults.Options); }
            Files.TextNew(path, rawJson);
            var entry = LibraryStore.Create(song, name, Files.Hash(path), builtin: true);
            entry.Id = entry.CatalogId = i <= 30 ? "builtin:" + name : "builtin:stable-legacy-synthetic-id-" + i;
            entry.AddedAt = DateTimeOffset.UnixEpoch.AddSeconds(i); entries.Add(entry);
        }
        LibraryCatalog.Build(Path.Combine(baseline, LibraryCatalog.FileName), entries, baseline);
        // Deliberately add an unknown legacy field and omit a default field in one metadata JSON.
        // A serialize/deserialize-only merge would silently alter this source object.
        using (var c = OpenCatalog(Path.Combine(baseline, LibraryCatalog.FileName), readOnly: false))
        {
            using var get = c.CreateCommand(); get.CommandText = "SELECT metadata_json FROM entries WHERE id='builtin:01.json'";
            var raw = JsonNode.Parse((string)get.ExecuteScalar()!)!.AsObject();
            raw["syntheticUnknownFieldMustSurvive"] = new JsonObject { ["description"] = "legacy fixture field" }; raw.Remove("favorite");
            using var update = c.CreateCommand(); update.CommandText = "UPDATE entries SET metadata_json=$json WHERE id='builtin:01.json'";
            update.Parameters.AddWithValue("$json", raw.ToJsonString()); update.ExecuteNonQuery();
        }
        var before = Files.Snapshot(baseline);
        var songs = new List<ManifestSong>();
        for (int i = 1; i <= 6; i++)
        {
            string id = i.ToString("D3"), midi = Path.Combine(input, id + ".mid"), reference = Path.Combine(input, id + ".reference.json");
            WriteFixture(midi, reference, i, i % 2 == 0 ? " melody " : "MELODY");
            songs.Add(new() { Id = id, Title = "合成曲谱夹具非真歌 " + id, Artist = "合成测试歌手 " + id,
                MidiPath = midi, ReferencePath = reference, SourceSha256 = Files.Hash(midi),
                SourceUrl = "https://example.invalid/synthetic-only/" + id, LanguageTags = i == 2 ? ["en"] : [] });
        }
        var manifest = new Manifest { Songs = songs, SourceCommit = "SYNTHETIC-FIXTURE-NOT-A-POP909-COMMIT", RetrievedAtUtc = new(2026, 10, 6, 0, 0, 0, TimeSpan.Zero) };
        string manifestPath = Path.Combine(input, "manifest.json"); Files.JsonNew(manifestPath, manifest);
        var inputBefore = Files.Snapshot(input);
        string build = Path.Combine(output, "synthetic-build"); BuildReport? report = null;
        Case("小夹具走同一build路径，6*9映射，6*3鼓阻止，抽5/10WAV，独立进程冷启/重启/搜索", () => {
            report = BuildRunner.Build(manifestPath, baseline, build, syntheticFixture: true);
            Files.Require(report.Status == "PASS_SYNTHETIC_ONLY" && report.Mappings.Count == 54 && report.Drums.Count == 18
                && report.Waves.Count == 10 && report.Mappings.Count(m => m.Sampled) == 45 && report.Songs.All(s => s.Timing.Passed), "矩阵/时序不完整");
        });
        Case("回归：旧谱文件无provenance，目录来源独立保留，Hash与ResourceHash不同", () => {
            string legacyRoot = Path.Combine(output, "legacy-no-provenance");
            string legacySongs = Path.Combine(legacyRoot, "Songs"); Directory.CreateDirectory(legacySongs);
            var original = new SongDocument { Title = "合成旧教学谱夹具（非真歌）", Author = "合成测试作者", Category = "测试",
                Source = "手写旧格式合成夹具，不是真歌", Description = "故意没有provenance字段，以复现教学谱与catalog来源分离。",
                LengthMs = 1250, Bpm = 96, Notes = [new(60, 0, 625, 0, 88), new(64, 625, 312.5, 0, 90)] };
            var raw = JsonNode.Parse(SongParser.ToJson(original))!.AsObject(); raw.Remove("provenance");
            string scorePath = Path.Combine(legacySongs, "01.json"); Files.TextNew(scorePath, raw.ToJsonString());
            var expected = LibraryStore.Create(original, "01.json", new string('A', 64), builtin: true);
            expected.Id = expected.CatalogId = "builtin:01.json"; expected.ResourceHash = Files.Hash(scorePath);
            expected.AddedAt = DateTimeOffset.UnixEpoch;
            expected.Provenance = new() { Provider = "qinban-demo", Synthetic = true, WorkId = "synthetic-legacy:01",
                Completeness = "exercise", SourceSha256 = expected.Hash, License = "unverified synthetic fixture only" };
            string catalog = Path.Combine(legacySongs, LibraryCatalog.FileName); LibraryCatalog.Build(catalog, [expected], legacySongs);
            var beforeLegacy = Files.Snapshot(legacySongs);
            var store = new LibraryStore(Path.Combine(legacyRoot, "direct-loader-UserData"), legacySongs);
            var loaded = store.LoadSong(store.Find(expected.Id)!);
            Files.Require(Files.Json(loaded.Provenance) != Files.Json(expected.Provenance)
                && Files.Json(loaded) == Files.Json(SongParser.Read(scorePath))
                && expected.Hash != expected.ResourceHash, "夹具未复现源谱与catalog来源分离");
            var verified = BuildRunner.VerifyStore(legacySongs, Path.Combine(legacyRoot, "verify-UserData"), [expected]);
            Files.Require(verified.Count == 1 && verified.MetadataRetained && verified.LazySearch, "旧谱verify失败");
            Files.SameSnapshot(legacySongs, beforeLegacy);
        });
        Case("固定种子抽样顺序可复现", () => {
            var ids = songs.Select(s => s.Id).Order(StringComparer.Ordinal).ToList(); var random = new Random(20261006);
            for (int i = ids.Count - 1; i > 0; i--) { int j = random.Next(i + 1); (ids[i], ids[j]) = (ids[j], ids[i]); }
            Files.Require(report != null && ids.Take(5).SequenceEqual(report.SampleIds), "抽样不可复现");
        });
        Case("baseline32谱与两条非文件名稳定ID不重写，教学builtin:01.json保留", () => {
            Files.SameSnapshot(baseline, before);
            var merged = Files.Read<List<LibraryEntry>>(Path.Combine(build, "expected-entries.json"));
            foreach (var e in entries) Files.Require(Files.Json(merged.Single(m => m.Id == e.Id)) == Files.Json(e), "基线元数据变化");
            foreach (var f in before.Where(f => f.RelativePath != LibraryCatalog.FileName))
                Files.Require(Files.Hash(Path.Combine(build, "Songs", f.RelativePath)) == f.Sha256, "基线复制变化");
        });
        Case("基线每条metadata_json原文不变，包括未知字段和遗漏的默认字段", () => {
            using var source = OpenCatalog(Path.Combine(baseline, LibraryCatalog.FileName));
            using var target = OpenCatalog(Path.Combine(build, "Songs", LibraryCatalog.FileName));
            using var command = source.CreateCommand(); command.CommandText = "SELECT id,metadata_json FROM entries ORDER BY id";
            using var reader = command.ExecuteReader(); int count = 0;
            while (reader.Read())
            {
                using var find = target.CreateCommand(); find.CommandText = "SELECT metadata_json FROM entries WHERE id=$id"; find.Parameters.AddWithValue("$id", reader.GetString(0));
                Files.Require(find.ExecuteScalar() as string == reader.GetString(1), "baseline metadata_json原文变化"); count++;
            }
            Files.Require(count == 32 && report!.BaselineMetadataUnchanged, "元数据未完全检查");
        });
        Case("默认只有MELODY；BRIDGE/PIANO/打击乐均完整保存", () => {
            Files.Require(report != null && report.Songs.All(s => s.SelectedTracks.SequenceEqual(new[] { 1 })
                && s.Tracks.Single(t => t.Id == 2).SourceNames.Contains("BRIDGE") && s.Tracks.Count == 5), "默认轨选择错误");
            foreach (var s in songs)
            {
                var score = SongParser.Read(Path.Combine(build, "Songs", "pop909-" + s.Id + ".json"));
                Files.Require(score.Notes.Select(n => n.Track).Distinct().Count() == 4 && score.Notes.Any(n => n.Percussion), "丢失其他轨");
            }
        });
        Case("变速tempo跨段音长与尾休止独立解析误差<=0.002ms", () => {
            Files.Require(report != null && report.Songs.All(s => s.Timing.TempoChanges == 2 && s.Timing.MaxDurationErrorMs <= .002
                && s.Timing.MaxOnsetErrorMs <= .002 && s.Timing.LengthErrorMs <= .002
                && s.LengthMs > Files.Read<ReferenceDocument>(songs.Single(x => x.Id == s.Id).ReferencePath).Notes.Max(n => n.StartMs + n.DurationMs)), "tempo/尾休止验证失败");
        });
        Case("referencePath、原MIDI、manifest、baseline全部保持SHA", () => { Files.SameSnapshot(input, inputBefore); Files.SameSnapshot(baseline, before); });
        Case("unknown语言不猜、已声明标签保留；不授CC0/不冒充审核/全部标synthetic", () => {
            foreach (var s in songs)
            {
                var score = SongParser.Read(Path.Combine(build, "Songs", "pop909-" + s.Id + ".json")); var p = score.Provenance;
                Files.Require(p.Artists.SequenceEqual(new[] { s.Artist }) && p.LanguageTags.SequenceEqual(s.LanguageTags)
                    && p.Synthetic && p.TimingStatus == "source-compared" && !p.RedistributionVerified && !p.IsFormalSong
                    && p.Completeness == "unknown" && p.MusicReview == "not-reviewed" && p.GameReview == "not-tested"
                    && p.License == BuildRunner.LicenseDeclaration && score.Author == "POP909钢琴编配（编配者未逐首标注）", "来源边界错误");
            }
        });
        Case("独立进程restart与冷启一致、搜索无eager parse，默认选轨保存", () => {
            Files.Require(report?.ColdStart is { LazySearch: true, Count: 38 } && report.Restart is { LazySearch: true, Count: 38 }
                && report.Restart.ProcessId != report.ColdStart.ProcessId && report.ColdStart.CatalogSha256 == report.Restart.CatalogSha256, "restart异常");
        });
        Case("WAV RIFF/PCM文件最多30秒，有SHA、片段标识、不播放音频", () => {
            Files.Require(report != null && report.Waves.Count == 10 && report.Waves.All(w => w.IsFragment && w.ActualWaveMs <= 30000.05
                && Files.Hash(Path.Combine(build, w.RelativePath)) == w.Sha256) && !report.AudioPlayed && report.NativeKeySendAttempts == 0, "WAV边界错误");
        });
        Case("长曲WAV截断不改完整计划，严格最多30秒", () => {
            string waveRoot = Path.Combine(output, "long-fragment"); Directory.CreateDirectory(waveRoot); Directory.CreateDirectory(Path.Combine(waveRoot, "wav"));
            var plan = new PlaybackPlan([new(60, 'A', 0, 40000, 40000, 90, 1, Sustain: true), new(64, 'D', 35000, 100, 100, 90, 1)], 120000, new(2, 2, 0, 0, 0, 0, 0), []);
            string original = Files.Json(plan); var wave = PlanChecks.RenderFragment("long-synthetic", "harmonic", plan, waveRoot);
            Files.Require(wave.PlannedNotes == 1 && Math.Abs(wave.ActualWaveMs - 30000) < .05 && wave.SourceEndMs == 29550
                && Files.Json(plan) == original, "截断污染原完整计划/超过30秒");
        });
        Case("长首休止自动从首音开始片段，不冒充从0开始", () => {
            string waveRoot = Path.Combine(output, "late-fragment"); Directory.CreateDirectory(waveRoot); Directory.CreateDirectory(Path.Combine(waveRoot, "wav"));
            var plan = new PlaybackPlan([new(60, 'A', 60000, 500, 500, 90, 1)], 100000, new(1, 1, 0, 0, 0, 0, 0), []);
            var wave = PlanChecks.RenderFragment("late-synthetic", "windsong", plan, waveRoot);
            Files.Require(wave.SourceStartMs == 60000 && wave.ActualWaveMs <= 30000.05, "首休止片段错误");
        });
        Case("已存在output拒绝且全部证据保持SHA", () => {
            var snapshot = Files.Snapshot(build); Reject(() => BuildRunner.Build(manifestPath, baseline, build, true)); Files.SameSnapshot(build, snapshot);
        });
        Case("正式build不接受6首合成小夹具，不产生output", () => {
            string target = Path.Combine(output, "rejected-production"); Reject(() => BuildRunner.Build(manifestPath, baseline, target, false));
            Files.Require(!Directory.Exists(target), "生产少于100首仍建库");
        });
        Case("统一默认移调消除七声音阶半音损耗，不改原谱且C调保持0", () => {
            var source = new SongDocument { Notes = new[] { 61, 63, 65, 66, 68, 70, 72 }.Select((p, i) => new NoteEvent(p, i * 500, 400, 1)).ToList() };
            string original = Files.Json(source); int shift = BuildRunner.ChooseStandardTranspose(source, [1]);
            var oldPlan = GameMapping.Build(source, new() { Tracks = [1] });
            var adapted = GameMapping.Build(source, new() { Tracks = [1], Transpose = shift });
            Files.Require(shift == -1 && oldPlan.Report.Accidentals > 0 && adapted.Report.Accidentals == 0 && Files.Json(source) == original, "移调不正确/修改原谱");
            var natural = new SongDocument { Notes = new[] { 60, 62, 64, 65, 67, 69, 71 }.Select((p,i) => new NoteEvent(p,i*500,400,1)).ToList() };
            Files.Require(BuildRunner.ChooseStandardTranspose(natural, [1]) == 0, "无需移调的C调被改变");
        });
        var native = SongParser.Read(songs[0].MidiPath); var goodRef = Files.Read<ReferenceDocument>(songs[0].ReferencePath);
        int rejectedReference = 0;
        void BadReference(string name, Func<ReferenceDocument, ReferenceDocument> mutate)
        {
            Case("reference拒绝: " + name, () => {
                var r = Files.Read<ReferenceDocument>(songs[0].ReferencePath); r = mutate(r);
                string path = Path.Combine(output, "bad-ref-" + name + ".json"); Files.JsonNew(path, r);
                Reject(() => PlanChecks.CompareReference(native, path, songs[0].SourceSha256)); rejectedReference++;
            });
        }
        ReferenceDocument Clone(ReferenceDocument r, List<NoteEvent>? notes = null, double? length = null, double? bpm = null, int? tempos = null, string? sha = null) => new() {
            Notes = notes ?? r.Notes, LengthMs = length ?? r.LengthMs, Bpm = bpm ?? r.Bpm, TempoChanges = tempos ?? r.TempoChanges,
            Reference = r.Reference, SourceSha256 = sha ?? r.SourceSha256
        };
        foreach (string property in new[] { "pitch", "track", "velocity", "percussion", "onset", "duration" })
            BadReference(property, r => {
                var list = r.Notes.ToList(); list[0] = property switch {
                    "pitch" => list[0] with { Pitch = list[0].Pitch + 1 }, "track" => list[0] with { Track = 7 },
                    "velocity" => list[0] with { Velocity = 80 }, "percussion" => list[0] with { Percussion = !list[0].Percussion },
                    "onset" => list[0] with { StartMs = list[0].StartMs + .01 }, _ => list[0] with { DurationMs = list[0].DurationMs + .01 }
                }; return Clone(r, notes: list);
            });
        BadReference("count", r => Clone(r, notes: r.Notes.Skip(1).ToList()));
        BadReference("length", r => Clone(r, length: r.LengthMs + .01));
        BadReference("bpm", r => Clone(r, bpm: r.Bpm + .01));
        BadReference("tempoChanges", r => Clone(r, tempos: 0));
        BadReference("sourceSha256", r => Clone(r, sha: new string('0', 64)));
        Case("reference小于容限误差允许且BPM误差合理", () => {
            var list = goodRef.Notes.Select(n => n with { StartMs = n.StartMs + .0001, DurationMs = n.DurationMs + .0001 }).ToList();
            string path = Path.Combine(output, "within-tolerance.json"); Files.JsonNew(path, Clone(goodRef, notes: list, length: goodRef.LengthMs + .0001, bpm: goodRef.Bpm + .0000001));
            Files.Require(PlanChecks.CompareReference(native, path, songs[0].SourceSha256).Passed, "容限内拒绝");
        });
        Case("reference失败不能留下source-compared POP谱，失败报告保留而非静默", () => {
            var changed = Files.Read<Manifest>(manifestPath); var targetInput = changed.Songs[0];
            changed.Songs[0] = Copy(targetInput, reference: Path.Combine(output, "bad-ref-pitch.json"));
            string path = Path.Combine(output, "bad-build-manifest.json"); Files.JsonNew(path, changed);
            string target = Path.Combine(output, "failed-build"); Reject(() => BuildRunner.Build(path, baseline, target, true));
            using var j = JsonDocument.Parse(File.ReadAllText(Path.Combine(target, "build-report.json")));
            Files.Require(j.RootElement.GetProperty("status").GetString() == "FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH"
                && !File.Exists(Path.Combine(target, "Songs", "pop909-001.json")), "失败竟认证谱/漏报告");
        });
        Case("MIDI错误SHA预检拒绝、不创建output", () => {
            var changed = Files.Read<Manifest>(manifestPath); changed.Songs[0] = Copy(changed.Songs[0], hash: new string('0', 64));
            string path = Path.Combine(output, "bad-hash-manifest.json"), target = Path.Combine(output, "bad-hash-build"); Files.JsonNew(path, changed);
            Reject(() => BuildRunner.Build(path, baseline, target, true)); Files.Require(!Directory.Exists(target), "错误SHA仍创建output");
        });
        Case("无MELODY的多轨输入明确失败，不默认全部伴奏", () => {
            string midi = Path.Combine(output, "no-melody.mid"), reference = Path.Combine(output, "no-melody.reference.json"); WriteFixture(midi, reference, 1, "NOT_MELODY");
            var changed = Files.Read<Manifest>(manifestPath); changed.Songs[0] = Copy(changed.Songs[0], midi: midi, reference: reference, hash: Files.Hash(midi));
            string path = Path.Combine(output, "no-melody-manifest.json"), target = Path.Combine(output, "no-melody-build"); Files.JsonNew(path, changed);
            Reject(() => BuildRunner.Build(path, baseline, target, true));
            Files.Require(File.ReadAllText(Path.Combine(target, "build-report.json")).Contains("缺少可用MELODY"), "失败原因不明确");
        });
        Case("最终输入/基线未变，所有负例确实被拒绝", () => { Files.SameSnapshot(input, inputBefore); Files.SameSnapshot(baseline, before); Files.Require(rejectedReference == 11, "负例数量不足"); });
        Files.JsonNew(Path.Combine(output, "self-test-report.json"), new {
            status = failures == 0 ? "PASS_SYNTHETIC_ONLY" : "FAIL", tests = cases.Count, failures, cases,
            synthetic = true, realSongsTested = 0, realIntegrationExecuted = false,
            fixtureSongs = songs.Count, melodicMappings = report?.Mappings.Count, blockedDrums = report?.Drums.Count,
            sampled = report?.SampleIds, fragmentWaves = report?.Waves.Count,
            referenceOrigin = "手写SMF tick/tempo日程的独立解析期望值；不调用SongParser/DryWetMidi生成reference；全部为非真歌合成数据。",
            audioPlayed = false, nativeKeySendAttempts = 0
        });
        Files.Require(failures == 0, $"Self-test有{failures}项失败，查看self-test-report.json");
        Console.WriteLine($"PASS {cases.Count} synthetic tests; real songs=0; native input=0; no audio playback; {output}");
    }
    private static SqliteConnection OpenCatalog(string path, bool readOnly = true)
    {
        var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path,
            Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWrite, Pooling = false }.ToString()); c.Open(); return c;
    }
    private static ManifestSong Copy(ManifestSong s, string? midi = null, string? reference = null, string? hash = null) => new() {
        Id = s.Id, Title = s.Title, Artist = s.Artist, MidiPath = midi ?? s.MidiPath, ReferencePath = reference ?? s.ReferencePath,
        SourceUrl = s.SourceUrl, SourceSha256 = hash ?? s.SourceSha256, LanguageTags = s.LanguageTags
    };
    private static void WriteFixture(string midiPath, string referencePath, int variation, string melodyName)
    {
        int ppq = 480, endTick = 3000, secondTempo = 666667 + variation;
        var notes = new List<FixtureNote> {
            new(1, 60, 0, 900, 100), new(1, 61, 960, 720, 90), new(1, 67, 1440, 600, 80), new(1, 79, 1800, 360, 95),
            new(1, 36, 2400, 120, 75), new(1, 96, 2640, 240, 85),
            new(2, 60, 240, 480, 65), new(2, 64, 240, 480, 65), new(2, 67, 240, 480, 65),
            new(3, 40, 120, 900, 70), new(4, 36, 360, 120, 110, true)
        };
        using var file = new FileStream(midiPath, FileMode.CreateNew, FileAccess.Write);
        void UInt16(int n) { Span<byte> b = stackalloc byte[2]; BinaryPrimitives.WriteUInt16BigEndian(b, (ushort)n); file.Write(b); }
        void UInt32(int n) { Span<byte> b = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(b, n); file.Write(b); }
        file.Write(Encoding.ASCII.GetBytes("MThd")); UInt32(6); UInt16(1); UInt16(5); UInt16(ppq);
        for (int track = 0; track < 5; track++)
        {
            var events = new List<(int Tick, int Priority, byte[] Event)>();
            string name = track switch { 0 => "CONDUCTOR", 1 => melodyName, 2 => "BRIDGE", 3 => "PIANO", _ => "DRUM" };
            var nameBytes = Encoding.ASCII.GetBytes(name); events.Add((0, -2, new byte[] { 0xff, 0x03, (byte)nameBytes.Length }.Concat(nameBytes).ToArray()));
            if (track == 0)
            {
                byte[] Tempo(int value) => [0xff, 0x51, 0x03, (byte)(value >> 16), (byte)(value >> 8), (byte)value];
                events.Add((0, -1, Tempo(500000))); events.Add((960, -1, Tempo(secondTempo)));
            }
            foreach (var n in notes.Where(n => n.Track == track))
            {
                int channel = n.Percussion ? 9 : track;
                events.Add((n.Start, 1, [(byte)(0x90 + channel), (byte)n.Pitch, (byte)n.Velocity]));
                events.Add((n.Start + n.Length, 0, [(byte)(0x80 + channel), (byte)n.Pitch, 0]));
            }
            using var chunk = new MemoryStream();
            void Vlq(int value)
            {
                var bytes = new List<byte> { (byte)(value & 127) };
                while ((value >>= 7) > 0) bytes.Insert(0, (byte)((value & 127) | 128)); chunk.Write(bytes.ToArray());
            }
            int last = 0;
            foreach (var e in events.OrderBy(e => e.Tick).ThenBy(e => e.Priority)) { Vlq(e.Tick - last); chunk.Write(e.Event); last = e.Tick; }
            Vlq(endTick - last); chunk.Write([0xff, 0x2f, 0]);
            file.Write(Encoding.ASCII.GetBytes("MTrk")); UInt32((int)chunk.Length); file.Write(chunk.ToArray());
        }
        file.Flush();
        double Metric(int tick) => tick <= 960 ? tick * 500000.0 / ppq / 1000 : 1000 + (tick - 960) * (double)secondTempo / ppq / 1000;
        Files.JsonNew(referencePath, new ReferenceDocument {
            Notes = notes.Select(n => new NoteEvent(n.Pitch, Metric(n.Start), Metric(n.Start + n.Length) - Metric(n.Start), n.Track, n.Velocity, n.Percussion))
                .OrderBy(n => n.Track).ThenBy(n => n.StartMs).ThenBy(n => n.Pitch).ThenBy(n => n.DurationMs).ThenBy(n => n.Velocity).ToList(),
            LengthMs = Metric(endTick), Bpm = 120, TempoChanges = 2,
            Reference = "SYNTHETIC ONLY: independent analytical integral of authored raw SMF tick/tempo schedule; not a real song"
        });
    }
}
