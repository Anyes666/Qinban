using System.Text.Json;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static partial class Program
{
    static (string Repo, string Output, List<LibraryEntry> Entries) ReadCommandInputs(string repoArg, string outputArg)
    {
        string repo = Path.GetFullPath(repoArg), output = Path.GetFullPath(outputArg);
        string allowed = Path.Combine(repo, ".validation", "pop100-gap-diagnosis-2026-10-06");
        Require(Path.GetDirectoryName(output) == allowed && Path.GetFileName(output).StartsWith("mapping-", StringComparison.Ordinal), "Output outside authorized mapping-* files");
        Require(!File.Exists(output), "Refusing to overwrite evidence"); Directory.CreateDirectory(allowed);
        var entries = new List<LibraryEntry>();
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder {
            DataSource = Path.Combine(repo, "Songs", "catalog.db"), Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "SELECT metadata_json FROM entries WHERE relative_path LIKE 'pop909-%' ORDER BY relative_path";
        using var reader = command.ExecuteReader();
        while (reader.Read()) entries.Add(JsonSerializer.Deserialize<LibraryEntry>(reader.GetString(0), JsonDefaults.Options)!);
        Require(entries.Count == 100, "Expected 100 catalog POP909 entries");
        return (repo, output, entries);
    }
    static int FocusedAllTracks(string repoArg, string outputArg)
    {
        var (repo, output, entries) = ReadCommandInputs(repoArg, outputArg);
        string catalog = Path.Combine(repo, "Songs", "catalog.db"), catalogHash = LibraryCatalog.HashFile(catalog);
        var rows = new List<object>(); var evidence = new List<object>();
        foreach (var entry in entries.Where(e => e.RelativePath is "pop909-035.json" or "pop909-038.json"))
        {
            string path = Path.Combine(repo, "Songs", entry.RelativePath), id = Path.GetFileNameWithoutExtension(entry.RelativePath).Replace("pop909-", "");
            string hash = LibraryCatalog.HashFile(path); Require(hash == entry.ResourceHash, "Catalog/source hash mismatch");
            var song = SongParser.Read(path); string before = Serialize(song), optsBefore = Serialize(entry.Options);
            foreach (var instrument in InstrumentCatalog.All.Where(i => i.CanAutoPlay))
            {
                var one = entry.Options.Copy(); one.InstrumentId = instrument.Id;
                var two = one.Copy(); two.Tracks = [1, 2]; var three = one.Copy(); three.Tracks = [1, 2, 3];
                CheckOptions(entry.Options, one, [1]); CheckOptions(entry.Options, two, [1, 2]); CheckOptions(entry.Options, three, [1, 2, 3]);
                var a = GameMapping.Build(song, one); var b = GameMapping.Build(song, two); var c = GameMapping.Build(song, three);
                int sa = ValidatePlan(song, one, a), sb = ValidatePlan(song, two, b), sc = ValidatePlan(song, three, c);
                Require(Metrics.Near(a.DurationMs, b.DurationMs) && Metrics.Near(a.DurationMs, c.DurationMs), "Full track timeline changed");
                Require(before == Serialize(song) && optsBefore == Serialize(entry.Options), "Source/options mutated");
                var track3 = song.Notes.Where(n => n.Track == 3 && !n.Percussion).ToList();
                var mapped3 = c.Notes.Where(n => n.Track == 3).ToList();
                rows.Add(new { id, title = song.Title, instrument = instrument.Id, originalOptions = one, candidateOptions = two, allTracksOptions = three,
                    original = Metrics.Plan(a, sa), candidate = Metrics.Plan(b, sb), allTracks = Metrics.Plan(c, sc),
                    melodyKeyOnsetRetention = Metrics.Delta(a, c), changeFromTracks12 = Metrics.Delta(b, c),
                    rawTrack3Notes = track3.Count, emittedAttributedTrack3Notes = mapped3.Count,
                    rawTrack3Sound = Metrics.Sound(Metrics.Spans(track3, three.Speed), song.DurationMs / three.Speed),
                    rawTrack3Onsets = Metrics.Onsets(track3.Select(n => n.StartMs / three.Speed)),
                    allTracksAttributedTrack3OverlapWithOriginalMelody = Metrics.GetOverlap(Metrics.Spans(a.Notes), Metrics.Spans(mapped3), mapped3.Select(n => n.StartMs)),
                    passed = true });
                Console.WriteLine($"PASS focused {id}/{instrument.Id}: [1] {a.Notes.Count}, [1,2] {b.Notes.Count}, [1,2,3] {c.Notes.Count}; first {c.Notes[0].StartMs:F3} ms, internal >=5s {Metrics.Sound(Metrics.Spans(c.Notes), c.DurationMs).CountGe5s}");
            }
            Require(hash == LibraryCatalog.HashFile(path) && before == Serialize(song), "Focused source changed");
            evidence.Add(new { id, path, sha256 = hash, sourceUnchanged = true, catalogOptionsUnchanged = optsBefore == Serialize(entry.Options) });
        }
        Require(rows.Count == 18 && catalogHash == LibraryCatalog.HashFile(catalog), "Focused coverage/catalog changed");
        WriteNew(output, Serialize(new { status = "PASS_FOCUSED_ALLTRACKS_18__MANUAL_OPTION_EVIDENCE_ONLY__NOT_MUSIC_OR_GAME_VALIDATED",
            generatedAt = DateTimeOffset.Now, repo, catalogSha256 = catalogHash,
            coreAssemblySha256 = LibraryCatalog.HashFile(typeof(GameMapping).Assembly.Location),
            summary = new { songs = 2, melodyInstruments = 9, allTracksPlans = 18, recheckedBaselinePlans = 36,
                actualGameMappingBuildCalls = 54, assertions, passedPlans = 18 }, sourceEvidence = evidence, rows,
            boundaries = new[] { "Only 035/038 Tracks=[1,2,3]; not 100-song all-tracks matrix", "No production/test/UserData edits, no OS input or playback",
                "SoundMs planned intervals, not measured game/waveform decay", "Original source notes unchanged does not imply original mapped keys/durations unchanged",
                "Raw track3 overlap and attributed output track3 overlap are not native-chord ownership decompositions" } }));
        return 0;
    }
    static int KeyOnsetChanges(string repoArg, string outputArg)
    {
        var (repo, output, entries) = ReadCommandInputs(repoArg, outputArg);
        string catalog = Path.Combine(repo, "Songs", "catalog.db"), catalogHash = LibraryCatalog.HashFile(catalog);
        var rows = new List<object>(); int removedCount = 0, classifiedNative = 0, affectedRows = 0, counterfactualCalls = 0;
        foreach (var entry in entries)
        {
            string path = Path.Combine(repo, "Songs", entry.RelativePath), hash = LibraryCatalog.HashFile(path);
            Require(hash == entry.ResourceHash, "Source/catalog hash mismatch");
            var song = SongParser.Read(path); string before = Serialize(song);
            foreach (var instrument in InstrumentCatalog.All.Where(i => i.CanAutoPlay))
            {
                var one = entry.Options.Copy(); one.InstrumentId = instrument.Id; var two = one.Copy(); two.Tracks = [1, 2];
                var a = GameMapping.Build(song, one); var b = GameMapping.Build(song, two);
                var bKeys = b.Notes.Select(n => (n.Key, n.StartMs)).ToHashSet(); var removed = a.Notes.Where(n => !bKeys.Contains((n.Key, n.StartMs))).ToList();
                if (removed.Count == 0) continue;
                affectedRows++; removedCount += removed.Count;
                var detail = removed.Select(n => {
                    var native = b.Notes.Where(p => p.StartMs == n.StartMs && p.ChordPitches != null).ToList();
                    if (native.Count > 0) classifiedNative++;
                    return new { original = n, candidateAtSameOnset = b.Notes.Where(p => p.StartMs == n.StartMs).ToList(),
                        selectedSourceAtOnset = song.Notes.Where(p => p.StartMs / two.Speed == n.StartMs && p.Track is 1 or 2).ToList(),
                        cause = native.Count > 0 ? "EXACT_NATIVE_CHORD_REPLACES_INDIVIDUAL_MELODY_KEY" : "UNCLASSIFIED_REQUIRES_REVIEW" };
                }).ToList();
                // Counterfactual invokes the actual mapper with native chords disabled ONLY in this diagnostic copy.
                // It is not a proposed production setting, not a copied mapper implementation.
                var noNative = two.Copy(); noNative.NativeGuitarChords = false;
                var check = GameMapping.Build(song, noNative); counterfactualCalls++;
                int checkShortened = ValidatePlan(song, noNative, check);
                var checkKeys = check.Notes.Select(n => (n.Key, n.StartMs)).ToHashSet();
                int stillRemoved = a.Notes.Count(n => !checkKeys.Contains((n.Key, n.StartMs)));
                Require(stillRemoved == 0, "Native-disabled counterfactual still removes original key/onset");
                rows.Add(new { id = Path.GetFileNameWithoutExtension(entry.RelativePath).Replace("pop909-", ""), song.Title, instrument = instrument.Id,
                    removedKeyOnsets = removed.Count, cause = "Native chord recognition from combined existing track1/2 exact pitch classes",
                    originalReport = a.Report, candidateReport = b.Report,
                    diagnosticCounterfactual = new { nativeGuitarChords = false, removedOriginalKeyOnsets = stillRemoved,
                        sourceUnchanged = true, shortenedSustainNotes = checkShortened, proposedProductionChange = false }, detail });
            }
            Require(before == Serialize(song) && hash == LibraryCatalog.HashFile(path), "Change diagnostic mutated source");
        }
        Require(removedCount == 436 && affectedRows == 40 && classifiedNative == removedCount, "Changed-onset count/native classification differs from matrix");
        Require(catalogHash == LibraryCatalog.HashFile(catalog), "Catalog changed");
        WriteNew(output, Serialize(new { status = "PASS_436_REMOVED_KEYONSETS_CLASSIFIED__NOT_LOSSLESS", generatedAt = DateTimeOffset.Now,
            summary = new { removedKeyOnsets = removedCount, classifiedNativeChordReplacements = classifiedNative, affectedRows,
                affectedSongs = 20, affectedInstruments = new[] { "ukulele", "euphonia" }, baselineMapperCalls = 1800,
                nativeDisabledCounterfactualCalls = counterfactualCalls, assertions }, rows,
            boundaries = new[] { "All 436 original keys occur at a native chord onset in the candidate, timing is retained",
                "Native-disabled diagnostic re-run retained all original key/onsets for these 40 rows",
                "Counterfactual is diagnosis only; source/production/defaults untouched", "Not full musical equivalence: native chord voicing and minimum duration differ" } }));
        Console.WriteLine($"PASS key-onset classification: {removedCount} keys / {affectedRows} rows; native-disabled diagnostic retains all");
        return 0;
    }
}
