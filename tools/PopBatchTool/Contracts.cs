using System.Text;
using System.Diagnostics.CodeAnalysis;
using System.Text.Json;
using System.Text.Json.Serialization;
using QinBan.Core;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class Manifest
{
    public required List<ManifestSong> Songs { get; init; }
    public string SourceCommit { get; init; } = "";
    public string SourceRecord { get; init; } = "";
    public required DateTimeOffset RetrievedAtUtc { get; init; }
    public string Provider { get; init; } = "";
    public string BatchKind { get; init; } = "";
    public string SourceUrl { get; init; } = "";
    public string License { get; init; } = "";
    public string LicenseUrl { get; init; } = "";
    public string RightsStatus { get; init; } = "";
    public string RightsNote { get; init; } = "";
    public bool? RedistributionVerified { get; init; }
    public string Author { get; init; } = "";
    public string Category { get; init; } = "";
    public string Description { get; init; } = "";
    public string IdPattern { get; init; } = "";
    public bool? SmartInterludesDefault { get; init; }
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class ManifestSong
{
    public required string Id { get; init; }
    public required string Title { get; init; }
    public required string Artist { get; init; }
    public required string MidiPath { get; init; }
    public required string ReferencePath { get; init; }
    public string SourceUrl { get; init; } = "";
    public required string SourceSha256 { get; init; }
    // SHA256 of the normalized MIDI/notation artifact; SourceSha256 remains the source record hash.
    public string NotationSha256 { get; init; } = "";
    public required List<string> LanguageTags { get; init; }
    public List<string> Artists { get; init; } = [];
    public string Provider { get; init; } = "";
    public string SourceCommit { get; init; } = "";
    public string SourceRecord { get; init; } = "";
    public string BatchKind { get; init; } = "";
    public string Author { get; init; } = "";
    public string Category { get; init; } = "";
    public string Description { get; init; } = "";
    public string IdPattern { get; init; } = "";
    public bool? SmartInterludes { get; init; }
    public string WorkId { get; init; } = "";
    public string EditionId { get; init; } = "";
    public string VersionLabel { get; init; } = "";
    public string License { get; init; } = "";
    public string LicenseUrl { get; init; } = "";
    public string RightsStatus { get; init; } = "";
    public string RightsNote { get; init; } = "";
    public string Album { get; init; } = "";
    public List<string> Aliases { get; init; } = [];
    public List<string> Tags { get; init; } = [];
    public string Completeness { get; init; } = "unknown";
    public string MusicReview { get; init; } = "not-reviewed";
    public string GameReview { get; init; } = "not-tested";
    public bool? RedistributionVerified { get; init; }
}

internal sealed record ManifestAuditSummary(string Provider, string BatchKind, bool LegacyPop909Compatibility,
    int SongCount, int DistinctWorkCount, int ManifestRedistributionVerifiedCount,
    List<string> OutputFiles, List<string> RightsStatuses);
internal sealed record FileEvidence(string RelativePath, string Sha256);
internal sealed record TrackEvidence(int Id, List<string> SourceNames, int Notes, bool Selected);
internal sealed record SongEvidence(string Id, string Title, string Artist, List<string> LanguageTags, string SourceUrl,
    string SourceSha256, string JsonSha256, int Notes, double LengthMs, double DurationMs, double Bpm,
    List<TrackEvidence> Tracks, List<int> SelectedTracks, TimingEvidence Timing, List<string> Warnings);
internal sealed record MappingEvidence(string Id, string Instrument, bool Sampled, bool Valid,
    int SourceNotes, int SelectedNotes, int ExcludedByTracks, int ExcludedPercussion,
    ConversionReport ConversionLoss, int SameKeySustainShortenings, List<string> Warnings);
internal sealed record DrumEvidence(string Id, string Instrument, bool Blocked, List<string> Warnings);
internal sealed record WaveEvidence(string Id, string Instrument, string RelativePath, string Sha256,
    double SourceStartMs, double SourceEndMs, double ActualWaveMs, int PlannedNotes, bool IsFragment,
    string Description);
internal sealed record StoreEvidence(int ProcessId, int Count, int Searches, int SongReads,
    LibraryStatistics Statistics, string CatalogSha256, bool LazySearch, bool MetadataRetained);

internal sealed class BuildReport
{
    public string Status { get; set; } = "IN_PROGRESS";
    public bool SyntheticFixture { get; init; }
    public string EvidenceClass => SyntheticFixture ? "SYNTHETIC_FIXTURE_ONLY_NOT_REAL_SONGS" : "LOCAL_CONVERSION_AND_NUMERICAL_MAPPING_ONLY";
    public DateTimeOffset StartedAtUtc { get; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? CompletedAtUtc { get; set; }
    public string SourceCommit { get; set; } = "";
    public string SourceRecord { get; set; } = "";
    public DateTimeOffset RetrievedAtUtc { get; set; }
    public string Provider { get; set; } = "";
    public string BatchKind { get; set; } = "";
    public string License { get; set; } = "";
    public string LicenseUrl { get; set; } = "";
    public string RightsStatus { get; set; } = "";
    public bool RedistributionVerified { get; set; }
    public bool? SmartInterludesDefault { get; set; }
    public string IntakeSchema { get; set; } = "PopBatchTool manifest-v2";
    public int Seed => 20261006;
    public string SamplingAlgorithm => "ID ordinal sort, seeded System.Random Fisher-Yates, first 5; net10.0";
    public bool IndependentSourceTimingVerified { get; set; }
    public bool MusicReviewed => false;
    public bool GameTested => false;
    public bool AudioPlayed => false;
    public int NativeKeySendAttempts => 0;
    public bool SourceFilesUnchanged { get; set; }
    public bool BaselineFilesUnchanged { get; set; }
    public bool BaselineMetadataUnchanged { get; set; }
    public bool NormalizedRoundTripPreserved { get; set; }
    public List<string> SampleIds { get; set; } = [];
    public List<SongEvidence> Songs { get; } = [];
    public List<MappingEvidence> Mappings { get; } = [];
    public List<DrumEvidence> Drums { get; } = [];
    public List<WaveEvidence> Waves { get; } = [];
    public StoreEvidence? ColdStart { get; set; }
    public StoreEvidence? Restart { get; set; }
    public List<string> Warnings { get; } = [
        "Reference timing is compared numerically; this is not human music review or in-game acceptance.",
        "Language tags come from the manifest; an empty list remains unknown and is not inferred.",
        "License, LicenseUrl, RightsStatus and RedistributionVerified are copied from the manifest/entry; the tool does not independently certify rights or grant redistribution permission.",
        "WAV files use Core synthesized tones; the tool does not play audio or send real input."
    ];
    public string? Failure { get; set; }
    public List<string> Failures { get; } = [];
}

internal static class Files
{
    public static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path, new UTF8Encoding(false, true)), JsonDefaults.Options)
        ?? throw new FormatException("JSON cannot be null: " + path);
    public static string Json<T>(T value) => JsonSerializer.Serialize(value, JsonDefaults.Options);
    public static void JsonNew<T>(string path, T value) => TextNew(path, Json(value));
    public static void TextNew(string path, string text)
    {
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        using var writer = new StreamWriter(stream, new UTF8Encoding(false)); writer.Write(text);
    }
    public static string Hash(string path) => LibraryCatalog.HashFile(path);
    public static void Require([DoesNotReturnIf(false)] bool value, string reason) { if (!value) throw new InvalidOperationException(reason); }
    public static bool Within(string path, string root) => Path.GetFullPath(path).StartsWith(
        Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    public static void NoLinks(string path)
    {
        for (var p = Path.GetFullPath(path); p != null; p = Path.GetDirectoryName(p))
            if (File.Exists(p) || Directory.Exists(p))
                Require((File.GetAttributes(p) & FileAttributes.ReparsePoint) == 0, "reparse points are not allowed: " + p);
    }
    public static List<FileEvidence> Snapshot(string root)
    {
        var files = new List<FileEvidence>();
        void Walk(string directory)
        {
            NoLinks(directory);
            foreach (var path in Directory.GetFileSystemEntries(directory).Order(StringComparer.Ordinal))
            {
                NoLinks(path);
                if (Directory.Exists(path)) Walk(path);
                else files.Add(new(Path.GetRelativePath(root, path), Hash(path)));
            }
        }
        Walk(root); return files;
    }
    public static void SameSnapshot(string root, List<FileEvidence> before) => Require(before.SequenceEqual(Snapshot(root)), "input directory changed: " + root);
}
