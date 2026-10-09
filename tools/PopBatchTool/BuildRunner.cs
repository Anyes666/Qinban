// Generic additive source batch; based on the proven Pop200Tool without modifying it.
using System.Buffers.Binary;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Melanchall.DryWetMidi.Core;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static class BuildRunner
{
    // Compatibility only for the already-existing POP909 manifest shape. Generic
    // providers must carry their own license and rights fields in the manifest.
    public const string LegacyPop909LicenseDeclaration = "POP909 repository MIT; underlying song redistribution unverified";
    private const string LegacyPop909RightsStatus = "unverified";
    // A 4,000+ score cold-start can exceed the old fixed two-minute probe window.
    // Keep the probe bounded, but leave enough time for deterministic SQLite/index startup.
    private const int RestartProbeTimeoutMs = 10 * 60 * 1000;
    private static readonly Regex GenericIdPattern = new("^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$", RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex LegacyPop909IdPattern = new("^[0-9]{3}$", RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex Sha256Pattern = new("^[A-Fa-f0-9]{64}$", RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex RightsStatusPattern = new("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private sealed record RightsPolicy(string License, string LicenseUrl, string RightsStatus, string RightsNote, bool RedistributionVerified);
    private sealed record ManifestContext(string Provider, string BatchKind, bool LegacyPop909, bool SmartInterludesDefault, IReadOnlyDictionary<string, RightsPolicy> Rights);
    private static string MidiSha256(ManifestSong song) =>
        string.IsNullOrWhiteSpace(song.NotationSha256) ? song.SourceSha256 : song.NotationSha256;

    public static BuildReport Build(string manifestPath, string baseline, string output, bool syntheticFixture)
    {
        manifestPath = Path.GetFullPath(manifestPath); baseline = Path.GetFullPath(baseline); output = Path.GetFullPath(output);
        Files.NoLinks(manifestPath); Files.NoLinks(baseline); Files.NoLinks(output);
        Files.Require(!File.Exists(output) && !Directory.Exists(output), "输出已存在，拒绝覆盖: " + output);
        Files.Require(!Files.Within(output, baseline) && !Files.Within(baseline, output)
            && !Files.Within(manifestPath, output), "输入输出目录不得重叠");
        Files.Require(Directory.Exists(baseline), "基线目录不存在");
        var manifest = Files.Read<Manifest>(manifestPath);
        Files.Require(!syntheticFixture, "本批次工具不允许合成谱绕过真实来源准入");
        var context = ValidateManifest(manifest, syntheticFixture, output);
        string manifestHash = Files.Hash(manifestPath);
        var baselineBefore = Files.Snapshot(baseline);
        var entries = ReadBaseline(baseline, out var baselineMetadata);
        var baselineSearchIndex = ReadBaselineSearchIndex(baseline);
        var baselineEntries = entries.ToList();
        var referenceHashes = manifest.Songs.ToDictionary(s => s.Id, s => Files.Hash(s.ReferencePath));
        Files.Require(!baselineBefore.Any(f => f.RelativePath.EndsWith("-wal", StringComparison.OrdinalIgnoreCase)
            || f.RelativePath.EndsWith("-shm", StringComparison.OrdinalIgnoreCase) || f.RelativePath.EndsWith("-journal", StringComparison.OrdinalIgnoreCase)),
            "拒绝有SQLite sidecar的非静态基线，请由主线提供稳定只读目录");
        // Atomically claim the directory with an exclusive marker; even concurrent builds must not share it.
        Directory.CreateDirectory(output);
        using var ownership = new FileStream(Path.Combine(output, ".popbatch-output-owner"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
        var report = new BuildReport {
            SyntheticFixture = syntheticFixture,
            SourceCommit = manifest.SourceCommit,
            SourceRecord = manifest.SourceRecord,
            RetrievedAtUtc = manifest.RetrievedAtUtc,
            Provider = context.Provider,
            BatchKind = context.BatchKind,
            License = SummarizePolicyValue(context.Rights.Values.Select(x => x.License)),
            LicenseUrl = SummarizePolicyValue(context.Rights.Values.Select(x => x.LicenseUrl)),
            RightsStatus = SummarizePolicyValue(context.Rights.Values.Select(x => x.RightsStatus)),
            RedistributionVerified = context.Rights.Values.All(x => x.RedistributionVerified),
            SmartInterludesDefault = context.SmartInterludesDefault
        };
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
                var rights = context.Rights[input.Id];
                string scoreStem = ScoreFileStem(context, input);
                Files.Require(Files.Hash(input.MidiPath).Equals(MidiSha256(input), StringComparison.OrdinalIgnoreCase), "MIDI SHA不符: " + input.Id);
                var song = SongParser.Read(input.MidiPath);
                string nativeNotes = Files.Json(song.Notes); double length = song.LengthMs, bpm = song.Bpm;
                var trackInfo = ReadTracks(input.MidiPath, song);
                var selected = trackInfo.Where(t => t.SourceNames.Any(n => n.Trim().Equals("MELODY", StringComparison.OrdinalIgnoreCase))
                    && song.Notes.Any(n => n.Track == t.Id && !n.Percussion)).Select(t => t.Id).ToList();
                var warnings = new List<string>(song.Warnings);
                if (selected.Count == 0)
                {
                    var melodicTracks = trackInfo.Where(t => song.Notes.Any(n => n.Track == t.Id && !n.Percussion)).ToList();
                    if (melodicTracks.Count == 1)
                    {
                        selected = [melodicTracks[0].Id];
                        warnings.Add("未发现MELODY，仅存在一条有旋律音符的轨道，默认选择该唯一轨；待人工确认。");
                    }
                    else if (!context.LegacyPop909 && melodicTracks.Count > 1)
                    {
                        // Generic MusicXML/MIDI sources often omit POP909's role labels.
                        // Retain every non-percussion source track rather than silently
                        // discarding accompaniment or inventing a melody track. The result
                        // remains a structural candidate and is explicitly marked for review.
                        selected = melodicTracks.Select(t => t.Id).ToList();
                        warnings.Add("来源未提供MELODY轨道标记；非POP结构化来源保留全部非打击乐轨道，避免丢失编配，需人工确认主旋律。");
                    }
                    else
                    {
                        Files.Require(false, "缺少可用MELODY，且多轨无法安全猜测；拒绝默认全部伴奏: " + input.Id);
                    }
                }
                if (selected.Count > 1) warnings.Add("发现多条MELODY，默认均选中；请人工复核旋律叠加。");
                if (song.Notes.Any(n => n.Percussion)) warnings.Add("保留打击乐音符，默认映射排除打击乐。");
                if (context.LegacyPop909)
                {
                song.Title = input.Title; song.Author = "POP909钢琴编配（编配者未逐首标注）";
                song.Category = "POP909 · 待音乐审核";
                song.Source = "POP909 MIDI / " + input.Id + " / commit " + manifest.SourceCommit;
                song.Description = "保留原MIDI全部音符、轨道与完整tempo map转换后的毫秒时序；默认以MELODY为主，继承POP909智能衔接；其他轨可手动勾选。"
                    + "tempo事件本身不能由Core原生notes JSON表示；参考文件中的tempoChanges仅作来源证据，不把该JSON导出MIDI当作原tempo曲线。";
                }
                else
                {
                    song.Title = input.Title; song.Author = context.Provider + " MIDI arrangement (arranger not individually labeled)";
                    song.Category = context.Provider + " - pending music review";
                    song.Source = context.Provider + " MIDI / " + input.Id + " / batch " + context.BatchKind + " / commit " + manifest.SourceCommit;
                    song.Description = "Preserves the source MIDI notes, tracks and millisecond timing derived from the complete tempo map; MELODY is selected by default and other tracks remain available for manual selection."
                        + "Tempo events are retained as reference evidence; Core native notes JSON does not encode the original tempo curve.";
                }
                song.Provenance = new() {
                    WorkId = input.WorkId, EditionId = input.EditionId,
                    Artist = input.Artist, Artists = input.Artists is { Count: > 0 } ? [.. input.Artists] : [input.Artist],
                    LanguageTags = [.. input.LanguageTags], Album = input.Album, VersionLabel = input.VersionLabel,
                    Provider = context.Provider,
                    Aliases = [.. input.Aliases], Tags = [.. input.Tags],
                    SourceUrl = input.SourceUrl, SourceSha256 = input.SourceSha256, NotationSha256 = MidiSha256(input), RetrievedAt = manifest.RetrievedAtUtc,
                    License = rights.License, LicenseUrl = rights.LicenseUrl, RightsStatus = rights.RightsStatus, Completeness = input.Completeness, TimingStatus = "unverified",
                    MusicReview = input.MusicReview, GameReview = input.GameReview,
                    RedistributionVerified = rights.RedistributionVerified, Synthetic = syntheticFixture
                };
                song.Warnings = warnings.Distinct().ToList();
                string fileName = scoreStem + ".json", targetScore = Path.Combine(songs, fileName);
                Files.Require(!File.Exists(targetScore), "与基线资源冲突: " + fileName);
                // Compare in memory before stamping, then again against the actual serialized native score.
                PlanChecks.CompareReference(song, input.ReferencePath, MidiSha256(input));
                song.Provenance.TimingStatus = "source-compared";
                Files.TextNew(targetScore, SongParser.ToJson(song));
                var normalized = SongParser.Read(targetScore);
                Files.Require(nativeNotes == Files.Json(normalized.Notes) && length == normalized.LengthMs && bpm == normalized.Bpm
                    && Files.Json(song) == Files.Json(normalized), "原谱notes/轨道/时序/元数据JSON往返变化: " + input.Id);
                var comparison = PlanChecks.CompareReference(normalized, input.ReferencePath, MidiSha256(input));
                Files.Require(comparison.ReferenceSha256 == referenceHashes[input.Id], "reference在转换期间变化");
                string hash = Files.Hash(targetScore);
                int defaultTranspose = ChooseStandardTranspose(song, selected);
                var entry = LibraryStore.Create(normalized, fileName, input.SourceSha256, builtin: true);
                entry.Id = entry.CatalogId = "builtin:" + fileName; entry.ResourceHash = hash;
                bool smartInterludes = input.SmartInterludes ?? context.SmartInterludesDefault;
                entry.AddedAt = manifest.RetrievedAtUtc; entry.Options = Defaults("windsong", selected, defaultTranspose); entry.Options.SmartInterludes = smartInterludes; entries.Add(entry);
                report.Songs.Add(new(input.Id, input.Title, input.Artist, input.LanguageTags, input.SourceUrl,
                    input.SourceSha256, hash, song.Notes.Count, song.LengthMs, song.DurationMs, song.Bpm,
                    trackInfo.Select(t => t with { Selected = selected.Contains(t.Id) }).ToList(), selected, comparison, warnings));
                bool sampled = samples.Contains(input.Id);
                foreach (var instrument in melodic)
                {
                    try
                    {
                        // Assess legacy manual mapping against selected source notes only. Do not
                        // Assess with smart handoff disabled, then persist the manifest/provider default for runtime.
                        var manualOptions = Defaults(instrument.Id, selected, defaultTranspose);
                        manualOptions.SmartInterludes = false;
                        var manualPlan = GameMapping.Build(song, manualOptions);
                        var assessment = PlanChecks.Assess(input.Id, song, instrument, manualOptions, manualPlan, sampled);
                        var options = Defaults(instrument.Id, selected, defaultTranspose);
                        options.SmartInterludes = smartInterludes;
                        var plan = sampled ? GameMapping.Build(song, options) : manualPlan;
                        Files.Require(nativeNotes == Files.Json(song.Notes) && song.LengthMs == length && song.Bpm == bpm
                            && Files.Json(song) == Files.Json(normalized), "映射修改源谱: " + input.Id + "/" + instrument.Id);
                        report.Mappings.Add(assessment);
                        if (sampled)
                        {
                            Files.JsonNew(Path.Combine(plans, $"{scoreStem}.{instrument.Id}.plan.json"), new {
                                input.Id, input.Title, input.Artist, input.SourceSha256, provider = context.Provider, rights, options,
                                manualAssessment = assessment, manualMappingOptions = manualOptions, plan, smartInterludesInherited = smartInterludes,
                                sourceNotes = song.Notes, distinctSourceDurations = song.Notes.Select(n => n.DurationMs).Distinct().Order().ToArray(),
                                distinctSoundDurations = plan.Notes.Select(n => n.SoundMs).Distinct().Order().ToArray(),
                                distinctHoldDurations = plan.Notes.Select(n => n.HoldMs).Distinct().Order().ToArray(),
                                lossMeaning = "源减输出含未选伴奏/打击乐、折叠/半音替换、和弦简化/同键合并/原生和弦压缩，不等同丢失旋律。",
                                noTransposeApplied = defaultTranspose == 0, evidenceClass = report.EvidenceClass
                            });
                            if (instrument.Id is "windsong" or "harmonic") report.Waves.Add(RenderFragment(context, input, instrument.Id, plan, output));
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
            int expectedWaveCount = Math.Min(5, manifest.Songs.Count) * 2;
            Files.Require(report.Failures.Count == 0 && report.Mappings.Count == manifest.Songs.Count * 9
                && report.Waves.Count == expectedWaveCount && report.Drums.Count == manifest.Songs.Count * 3, "??/????????????failures");
            Files.JsonNew(Path.Combine(output, "expected-entries.json"), entries);
            Files.Require(entries.Count == baselineEntries.Count + manifest.Songs.Count, "新曲库条目数必须等于基线+本批来源谱");
            string catalog = Path.Combine(songs, LibraryCatalog.FileName);
            Files.Require(!File.Exists(catalog), "拒绝覆盖目录数据库");
            LibraryCatalog.Build(catalog, entries, songs);
            PreserveBaselineMetadata(catalog, baselineMetadata);
            PreserveBaselineSearchIndex(catalog, baselineSearchIndex);
            report.BaselineMetadataUnchanged = true;
            string data = Path.Combine(output, "isolated-UserData");
            report.ColdStart = VerifyStore(songs, data, entries);
            // Exercise options persistence before the process restart, never touching real UserData.
            var store = new LibraryStore(data, songs);
            foreach (var e in entries.Where(IsSourceBackedEntry)) store.Save(store.Find(e.Id)!);
            report.Restart = SpawnRestart(songs, data, Path.Combine(output, "expected-entries.json"), output);
            Files.Require(report.ColdStart.CatalogSha256 == report.Restart.CatalogSha256, "建库冷启/重启改变catalog");
            foreach (var input in manifest.Songs)
            {
                Files.Require(Files.Hash(input.MidiPath).Equals(MidiSha256(input), StringComparison.OrdinalIgnoreCase), "源MIDI变化: " + input.Id);
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
                $"PopBatchTool output; provider={context.Provider}; batchKind={context.BatchKind}. Failed or partial output must not be published; see build-report.json.\n"
                + "Timing evidence is a numerical comparison against the manifest-provided reference; this is not human music review or in-game acceptance.\n"
                + "License, license URL, rights status and redistribution flag are copied from the manifest/entry; the tool does not independently certify rights or grant redistribution permission.\n"
                + "MELODY selection is conservative; other tracks are retained. Unknown language tags are not inferred.\n"
                + "WAV files are at most 30-second synthesized previews; the tool does not play audio or send real input.\n"
                + (syntheticFixture ? "Synthetic fixtures are not real songs and do not count toward a library.\n" : "The main line must independently inspect JSON/SHA/catalog output; this tool does not install or publish.\n"));
        }
        return report;
    }
    public static PlayOptions Defaults(string instrument, List<int> tracks, int transpose = 0) => new() {
        InstrumentId = instrument, Transpose = transpose, Tracks = [.. tracks], ExcludePercussion = true, Speed = 1, Octave = 0,
        HoldByScore = true, Chords = ChordMode.Simultaneous, MaxChordNotes = 5, Accidentals = AccidentalMode.Nearest, Range = RangeMode.FoldOctaves
    };
    public static ManifestAuditSummary ValidateManifestOnly(string manifestPath)
    {
        manifestPath = Path.GetFullPath(manifestPath);
        Files.NoLinks(manifestPath);
        var manifest = Files.Read<Manifest>(manifestPath);
        var context = ValidateManifest(manifest, fixture: false, output: null);
        return new(
            context.Provider,
            context.BatchKind,
            context.LegacyPop909,
            manifest.Songs.Count,
            manifest.Songs.Select(s => s.WorkId).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            context.Rights.Values.Count(r => r.RedistributionVerified),
            manifest.Songs.OrderBy(s => s.Id, StringComparer.OrdinalIgnoreCase)
                .Select(s => ScoreFileName(context, s)).ToList(),
            context.Rights.Values.Select(r => r.RightsStatus).Distinct(StringComparer.OrdinalIgnoreCase).Order().ToList());
    }

    private static ManifestContext ValidateManifest(Manifest manifest, bool fixture, string? output)
    {
        Files.Require(manifest.Songs != null
            && (fixture ? manifest.Songs.Count is >= 1 and <= 10 : manifest.Songs.Count is >= 1 and <= 5000),
            "manifest must contain 1..5000 source songs (fixture limit is 10)");
        Files.Require(!string.IsNullOrWhiteSpace(manifest.SourceCommit) && manifest.SourceCommit.Length <= 256
            && !manifest.SourceCommit.Any(char.IsControl), "sourceCommit is missing or invalid");
        Files.Require(manifest.RetrievedAtUtc != default && manifest.RetrievedAtUtc.Offset == TimeSpan.Zero,
            "retrievedAtUtc must be explicit UTC");
        string provider = (manifest.Provider ?? "").Trim();
        string batchKind = (manifest.BatchKind ?? "").Trim();
        ValidateDisplayText(provider, 128, "provider");
        ValidateDisplayText(batchKind, 256, "batchKind");
        Files.Require(!string.IsNullOrWhiteSpace(provider), "manifest.Provider is required; no provider default is applied");
        Files.Require(!string.IsNullOrWhiteSpace(batchKind), "manifest.BatchKind is required; no source batch default is applied");
        Files.Require(manifest.Songs!.All(s => s != null), "manifest contains a null song entry");

        bool legacyPop909 = provider.Equals("POP909", StringComparison.OrdinalIgnoreCase);
        if (legacyPop909)
            Files.Require(manifest.Songs.All(s => IsLegacyPop909Id(s.Id)),
                "provider POP909 is accepted only with its legacy 001..909 IDs; use another provider for generic IDs");

        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var editions = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var outputNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var rights = new Dictionary<string, RightsPolicy>(StringComparer.OrdinalIgnoreCase);
        foreach (var s in manifest.Songs)
        {
            Files.Require(s != null, "manifest song cannot be null");
            Files.Require(ids.Add(s.Id), "duplicate song ID: " + s.Id);
            if (legacyPop909)
                Files.Require(IsLegacyPop909Id(s.Id), "POP909 ID must be 001..909: " + s.Id);
            else
                Files.Require(IsStableId(s.Id), "song ID must be a stable filename-safe token: " + s.Id);

            ValidateDisplayText(s.Title, 1000, "title");
            ValidateDisplayText(s.Artist, 1000, "artist");
            Files.Require(!string.IsNullOrWhiteSpace(s.Title) && !string.IsNullOrWhiteSpace(s.Artist),
                "title and artist are required: " + s.Id);
            Files.Require(s.LanguageTags != null && s.Artists != null && s.Aliases != null && s.Tags != null,
                "metadata lists cannot be null: " + s.Id);
            ValidateVersionLabel(s.VersionLabel, s.Id);
            Files.Require(IsStableIdentity(s.WorkId), "WorkId must be a stable identity token: " + s.Id);
            Files.Require(IsStableIdentity(s.EditionId), "EditionId must be a stable identity token: " + s.Id);
            Files.Require(editions.Add(s.EditionId), "duplicate EditionId: " + s.EditionId);

            Files.Require(!string.IsNullOrWhiteSpace(s.SourceUrl) && IsHttpUrl(s.SourceUrl),
                "sourceUrl must be an explicit http/https URL: " + s.Id);
            Files.Require(!string.IsNullOrWhiteSpace(s.SourceSha256)
                && Sha256Pattern.IsMatch(s.SourceSha256),
                "sourceSha256 must be 64 hex characters: " + s.Id);
            Files.Require(string.IsNullOrWhiteSpace(s.NotationSha256)
                || Sha256Pattern.IsMatch(s.NotationSha256),
                "notationSha256 must be empty or 64 hex characters: " + s.Id);
            foreach (string path in new[] { s.MidiPath, s.ReferencePath })
            {
                Files.Require(!string.IsNullOrWhiteSpace(path) && Path.IsPathFullyQualified(path) && File.Exists(path),
                    "MIDI/reference must be existing absolute paths: " + s.Id);
                Files.NoLinks(path);
                if (output != null)
                    Files.Require(!Files.Within(path, output), "source input cannot be inside output: " + path);
            }
            Files.Require(Path.GetExtension(s.MidiPath).ToLowerInvariant() is ".mid" or ".midi",
                "only source MIDI files are accepted: " + s.Id);
            Files.Require(!s.Id.EndsWith(".json", StringComparison.OrdinalIgnoreCase),
                "song ID must not include the JSON extension: " + s.Id);
            string outputName = ScoreFileName(legacyPop909, s.Id);
            Files.Require(outputNames.Add(outputName), "song IDs map to the same output JSON filename: " + outputName);

            Files.Require(s.MusicReview == "not-reviewed" && s.GameReview == "not-tested",
                "this tool only carries source timing evidence; music/game review claims are not accepted: " + s.Id);
            var policy = ResolveRights(manifest, s, legacyPop909);
            rights.Add(s.Id, policy);
            var artists = s.Artists is { Count: > 0 } ? s.Artists : [s.Artist];
            new ScoreProvenance {
                WorkId = s.WorkId, EditionId = s.EditionId, Artist = s.Artist, Artists = [.. artists],
                LanguageTags = [.. s.LanguageTags], Album = s.Album, VersionLabel = s.VersionLabel,
                Aliases = [.. s.Aliases], Tags = [.. s.Tags], Provider = provider,
                SourceUrl = s.SourceUrl, SourceSha256 = s.SourceSha256, NotationSha256 = MidiSha256(s), License = policy.License,
                LicenseUrl = policy.LicenseUrl, RightsStatus = policy.RightsStatus, Completeness = s.Completeness,
                MusicReview = s.MusicReview, GameReview = s.GameReview,
                RedistributionVerified = policy.RedistributionVerified
            }.Validate();
            Files.Require(Files.Hash(s.MidiPath).Equals(MidiSha256(s), StringComparison.OrdinalIgnoreCase),
                "source MIDI SHA256 does not match manifest: " + s.Id);
        }

        foreach (var group in manifest.Songs.GroupBy(s => s.WorkId, StringComparer.OrdinalIgnoreCase).Where(g => g.Count() > 1))
        {
            Files.Require(group.All(s => !string.IsNullOrWhiteSpace(s.VersionLabel)),
                "multiple editions of one WorkId require non-empty versionLabel: " + group.Key);
            Files.Require(group.Select(s => s.VersionLabel).Distinct(StringComparer.OrdinalIgnoreCase).Count() == group.Count(),
                "multiple editions of one WorkId require distinct versionLabel values: " + group.Key);
        }

        return new(provider, batchKind, legacyPop909, manifest.SmartInterludesDefault ?? legacyPop909, rights);
    }

    private static RightsPolicy ResolveRights(Manifest manifest, ManifestSong song, bool legacyPop909)
    {
        string license = FirstNonBlank(song.License, manifest.License);
        string licenseUrl = FirstNonBlank(song.LicenseUrl, manifest.LicenseUrl);
        string rightsStatus = FirstNonBlank(song.RightsStatus, manifest.RightsStatus);
        string rightsNote = FirstNonBlank(song.RightsNote, manifest.RightsNote);
        bool redistributionVerified = song.RedistributionVerified ?? manifest.RedistributionVerified ?? false;

        if (legacyPop909 && string.IsNullOrWhiteSpace(license) && string.IsNullOrWhiteSpace(licenseUrl)
            && string.IsNullOrWhiteSpace(rightsStatus) && string.IsNullOrWhiteSpace(rightsNote)
            && !redistributionVerified)
        {
            license = LegacyPop909LicenseDeclaration;
            rightsStatus = LegacyPop909RightsStatus;
            redistributionVerified = false;
        }

        Files.Require(!string.IsNullOrWhiteSpace(license) && license.Length <= 4096 && !license.Any(char.IsControl),
            "license must be declared by the manifest/entry: " + song.Id);
        Files.Require(string.IsNullOrWhiteSpace(licenseUrl) || IsHttpUrl(licenseUrl),
            "licenseUrl must be http/https when present: " + song.Id);
        Files.Require(!string.IsNullOrWhiteSpace(rightsStatus) && RightsStatusPattern.IsMatch(rightsStatus),
            "rightsStatus must be a stable status token: " + song.Id);
        Files.Require(rightsNote.Length <= 4096 && !rightsNote.Any(char.IsControl),
            "rightsNote is invalid: " + song.Id);
        if (redistributionVerified)
            Files.Require(!rightsStatus.Equals("unverified", StringComparison.OrdinalIgnoreCase)
                && !rightsStatus.Equals("unknown", StringComparison.OrdinalIgnoreCase)
                && !rightsStatus.Equals("not-stated", StringComparison.OrdinalIgnoreCase),
                "redistributionVerified=true cannot use an unknown/unverified rightsStatus: " + song.Id);
        return new(license, licenseUrl, rightsStatus, rightsNote, redistributionVerified);
    }

    private static string FirstNonBlank(string entry, string batch) =>
        string.IsNullOrWhiteSpace(entry) ? (batch ?? "").Trim() : entry.Trim();

    private static string SummarizePolicyValue(IEnumerable<string> values)
    {
        var distinct = values.Where(v => !string.IsNullOrWhiteSpace(v)).Distinct(StringComparer.OrdinalIgnoreCase).Order().ToList();
        return distinct.Count switch { 0 => "", 1 => distinct[0], _ => "<mixed>" };
    }

    private static bool IsHttpUrl(string value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && uri.Host.Length > 0 && uri.Scheme is "https" or "http";

    private static bool IsLegacyPop909Id(string id) =>
        !string.IsNullOrWhiteSpace(id) && LegacyPop909IdPattern.IsMatch(id)
        && int.TryParse(id, out var number) && number is >= 1 and <= 909;

    private static bool IsStableId(string value) => !string.IsNullOrWhiteSpace(value) && GenericIdPattern.IsMatch(value);
    private static bool IsStableIdentity(string value) => !string.IsNullOrWhiteSpace(value)
        && value == value.Trim() && value.Length <= 256 && !value.Any(char.IsControl)
        && !value.Any(char.IsWhiteSpace) && !value.Contains(Path.DirectorySeparatorChar)
        && !value.Contains(Path.AltDirectorySeparatorChar);

    private static void ValidateDisplayText(string value, int maxLength, string field)
    {
        Files.Require(value != null && value.Length <= maxLength && !value.Any(char.IsControl), field + " is invalid");
    }

    private static void ValidateVersionLabel(string value, string id)
    {
        if (string.IsNullOrWhiteSpace(value)) return;
        Files.Require(value == value.Trim() && value.Length <= 256 && !value.Any(char.IsControl),
            "versionLabel is invalid: " + id);
    }

    private static string ScoreFileName(bool legacyPop909, string id) =>
        legacyPop909 ? "pop909-" + id + ".json" : id + ".json";

    private static string ScoreFileName(ManifestContext context, ManifestSong song) => ScoreFileName(context.LegacyPop909, song.Id);
    private static string ScoreFileStem(ManifestContext context, ManifestSong song) =>
        Path.GetFileNameWithoutExtension(ScoreFileName(context, song));

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
    private static WaveEvidence RenderFragment(ManifestContext context, ManifestSong song, string instrument,
        PlaybackPlan plan, string output)
    {
        var wave = PlanChecks.RenderFragment(song.Id, instrument, plan, output);
        string desiredRelative = Path.Combine("wav", $"{ScoreFileStem(context, song)}.{instrument}.fragment-max30s.wav");
        string actualPath = Path.Combine(output, wave.RelativePath);
        string desiredPath = Path.Combine(output, desiredRelative);
        if (!actualPath.Equals(desiredPath, StringComparison.OrdinalIgnoreCase))
        {
            Files.Require(File.Exists(actualPath), "rendered preview is missing: " + actualPath);
            Files.Require(!File.Exists(desiredPath), "preview output collision: " + desiredPath);
            File.Move(actualPath, desiredPath);
            Files.Require(Files.Hash(desiredPath).Equals(wave.Sha256, StringComparison.OrdinalIgnoreCase),
                "renamed preview SHA changed: " + song.Id + "/" + instrument);
            wave = wave with { RelativePath = desiredRelative };
        }
        return wave;
    }

    private static bool IsSourceBackedEntry(LibraryEntry entry) =>
        entry.BuiltIn && !string.IsNullOrWhiteSpace(entry.Provenance.Provider)
        && !string.IsNullOrWhiteSpace(entry.Provenance.SourceUrl)
        && Sha256Pattern.IsMatch(entry.Provenance.SourceSha256 ?? "")
        && !string.IsNullOrWhiteSpace(entry.Provenance.WorkId)
        && !string.IsNullOrWhiteSpace(entry.Provenance.EditionId)
        && entry.Provenance.TimingStatus == "source-compared";

    private static List<LibraryEntry> ReadBaseline(string root, out Dictionary<string, string> metadata)
    {
        metadata = new(StringComparer.Ordinal);
        string catalog = Path.Combine(root, LibraryCatalog.FileName); Files.Require(File.Exists(catalog), "必须提供已有catalog.db，不可用fallback猜ID");
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
        Files.Require(result.Count > 0 && result.Select(e => e.RelativePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() == result.Count
            && result.Any(e => e.Id == "builtin:01.json"), "基线必须有独立资源并保留builtin:01.json");
        return result;
    }
    private static Dictionary<string, object?[]> ReadBaselineSearchIndex(string root)
    {
        string catalog = Path.Combine(root, LibraryCatalog.FileName);
        using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = catalog, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()); c.Open();
        using var command = c.CreateCommand();
        command.CommandText = "SELECT entry_id,title_key,author_key,search_text,pinyin,initials,sort_title,duration,added_ms,provider,timing_verified,completeness,human_reviewed FROM search_index ORDER BY entry_id";
        using var reader = command.ExecuteReader();
        var result = new Dictionary<string, object?[]>(StringComparer.Ordinal);
        while (reader.Read())
        {
            var values = new object?[reader.FieldCount];
            reader.GetValues(values);
            string id = Convert.ToString(values[0]) ?? throw new FormatException("baseline search index entry_id??");
            Files.Require(result.TryAdd(id, values), "baseline search index entry_id??: " + id);
        }
        Files.Require(result.Count > 0, "baseline search_index??");
        return result;
    }
    private static void PreserveBaselineSearchIndex(string catalog, Dictionary<string, object?[]> rows)
    {
        using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = catalog, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString()); c.Open();
        using var tx = c.BeginTransaction();
        foreach (var (id, values) in rows)
        {
            using var update = c.CreateCommand(); update.Transaction = tx;
            update.CommandText = "UPDATE search_index SET title_key=$title,author_key=$author,search_text=$search,pinyin=$pinyin,initials=$initials,sort_title=$sort,duration=$duration,added_ms=$added,provider=$provider,timing_verified=$timing,completeness=$complete,human_reviewed=$human WHERE entry_id=$id";
            update.Parameters.AddWithValue("$id", id);
            update.Parameters.AddWithValue("$title", values[1] ?? DBNull.Value);
            update.Parameters.AddWithValue("$author", values[2] ?? DBNull.Value);
            update.Parameters.AddWithValue("$search", values[3] ?? DBNull.Value);
            update.Parameters.AddWithValue("$pinyin", values[4] ?? DBNull.Value);
            update.Parameters.AddWithValue("$initials", values[5] ?? DBNull.Value);
            update.Parameters.AddWithValue("$sort", values[6] ?? DBNull.Value);
            update.Parameters.AddWithValue("$duration", values[7] ?? DBNull.Value);
            update.Parameters.AddWithValue("$added", values[8] ?? DBNull.Value);
            update.Parameters.AddWithValue("$provider", values[9] ?? DBNull.Value);
            update.Parameters.AddWithValue("$timing", values[10] ?? DBNull.Value);
            update.Parameters.AddWithValue("$complete", values[11] ?? DBNull.Value);
            update.Parameters.AddWithValue("$human", values[12] ?? DBNull.Value);
            Files.Require(update.ExecuteNonQuery() == 1, "baseline search index????ID: " + id);
        }
        tx.Commit();
        foreach (var (id, values) in rows)
        {
            using var read = c.CreateCommand();
            read.CommandText = "SELECT title_key,author_key,search_text,pinyin,initials,sort_title,duration,added_ms,provider,timing_verified,completeness,human_reviewed FROM search_index WHERE entry_id=$id";
            read.Parameters.AddWithValue("$id", id);
            using var reader = read.ExecuteReader();
            Files.Require(reader.Read(), "?????baseline search index: " + id);
            for (int i = 0; i < reader.FieldCount; i++)
            {
                object actual = reader.GetValue(i); object expected = values[i + 1] ?? DBNull.Value;
                Files.Require((actual is DBNull ? DBNull.Value : actual).Equals(expected), "baseline search index??: " + id + "/" + i);
            }
        }
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
    private static string BoundedSearch(string value, int limit = 16)
    {
        var terms = LibrarySearch.Normalize(value).Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Distinct(StringComparer.Ordinal).Take(limit);
        return string.Join(" ", terms);
    }

    private static string BoundedCombinedSearch(LibraryEntry entry)
    {
        string title = BoundedSearch(entry.Title, 12);
        string artist = BoundedSearch(entry.Provenance.Artist, 4);
        return string.Join(" ", new[] { title, artist }.Where(s => !string.IsNullOrWhiteSpace(s)));
    }    public static StoreEvidence VerifyStore(string songs, string data, List<LibraryEntry> expected)
    {
        Files.NoLinks(songs); Files.NoLinks(data); var store = new LibraryStore(data, songs);
        Files.Require(store.Count == expected.Count && !store.MigratedLegacy && store.LoadWarnings.Count == 0, "隔离LibraryStore数量/迁移/警告不正确");
        int searches = 0;
        foreach (var e in expected)
        {
            var actual = store.Find(e.Id); Files.Require(actual != null && Files.Json(actual) == Files.Json(e), "稳定ID/元数据/Options未保留: " + e.Id);
            if (!IsSourceBackedEntry(e)) continue;
            string boundedTitle = BoundedSearch(e.Title);
            string boundedArtist = BoundedSearch(e.Provenance.Artist);
            string boundedCombined = BoundedCombinedSearch(e);
            foreach (string term in new[] { boundedTitle, boundedArtist, boundedCombined }.Where(s => !string.IsNullOrWhiteSpace(s)))
            {
                // Use WorkId to make common-title/common-artist searches valid without assuming unique artists.
                // LibrarySearch intentionally caps queries at 16 terms; long source titles are bounded deterministically.
                // A WorkId can legitimately contain many editions; page through the real result set instead of
                // assuming the target edition is on the first 50 rows.
                var page = store.Query(new(Search: term, WorkId: e.Provenance.WorkId)); searches++;
                bool found = page.Items.Any(item => item.Id == e.Id);
                for (int offset = page.Limit; !found && offset < page.Total; offset += page.Limit)
                {
                    page = store.Query(new(Search: term, WorkId: e.Provenance.WorkId, Offset: offset, Limit: page.Limit)); searches++;
                    found = page.Items.Any(item => item.Id == e.Id);
                }
                Files.Require(page.Total > 0 && found, "??/??/???????????: " + e.Id + " / " + term);
            }
            var global = store.Query(new(Search: boundedCombined, Limit: 50)); searches++;
            Files.Require(global.Total > 0, "全库组合搜索为空");
            for (int offset = 0; offset < global.Total; offset += 50)
            {
                var page = store.Query(new(Search: boundedCombined, Offset: offset, Limit: 50)); searches++;
                if (page.Items.Any(x => x.Id == e.Id)) break;
                Files.Require(offset + 50 < global.Total, "全库搜索未找到目标ID");
            }
            Files.Require(!e.Provenance.IsFormalSong && e.Provenance.TimingStatus == "source-compared"
                && e.Provenance.MusicReview == "not-reviewed" && e.Provenance.GameReview == "not-tested"
                && !string.IsNullOrWhiteSpace(e.Provenance.Provider)
                && IsHttpUrl(e.Provenance.SourceUrl)
                && Regex.IsMatch(e.Provenance.SourceSha256 ?? "", "^[A-Fa-f0-9]{64}$")
                && !string.IsNullOrWhiteSpace(e.Provenance.License)
                && e.Options.Tracks is { Count: > 0 } && !string.IsNullOrWhiteSpace(e.Provenance.WorkId)
                && !string.IsNullOrWhiteSpace(e.Provenance.EditionId), "source provenance/default invalid");
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
            if (IsSourceBackedEntry(e))
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
        if (!child.WaitForExit(RestartProbeTimeoutMs)) { child.Kill(entireProcessTree: true); throw new TimeoutException($"owned restart helper timeout {RestartProbeTimeoutMs / 1000}s"); }
        Task.WaitAll(stdout, stderr);
        Files.TextNew(Path.Combine(output, "restart.stdout.log"), stdout.Result); Files.TextNew(Path.Combine(output, "restart.stderr.log"), stderr.Result);
        Files.Require(child.ExitCode == 0, "restart helper failed: " + stderr.Result);
        var result = Files.Read<StoreEvidence>(report);
        Files.Require(result.ProcessId == child.Id && result.ProcessId != Environment.ProcessId, "不是独立进程restart");
        return result;
    }
}
