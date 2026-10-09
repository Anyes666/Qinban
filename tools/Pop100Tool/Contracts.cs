using System.Text;
using System.Diagnostics.CodeAnalysis;
using System.Text.Json;
using System.Text.Json.Serialization;
using QinBan.Core;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class Manifest
{
    public required List<ManifestSong> Songs { get; init; }
    public required string SourceCommit { get; init; }
    public required DateTimeOffset RetrievedAtUtc { get; init; }
}
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class ManifestSong
{
    public required string Id { get; init; }
    public required string Title { get; init; }
    public required string Artist { get; init; }
    public required string MidiPath { get; init; }
    public required string ReferencePath { get; init; }
    public required string SourceUrl { get; init; }
    public required string SourceSha256 { get; init; }
    public required List<string> LanguageTags { get; init; }
}
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
    public DateTimeOffset RetrievedAtUtc { get; set; }
    public int Seed => 20261006;
    public string SamplingAlgorithm => "ID ordinal sort, seeded System.Random Fisher-Yates, first 5; net10.0";
    public bool IndependentSourceTimingVerified { get; set; }
    public bool MusicReviewed => false;
    public bool GameTested => false;
    public bool RedistributionVerified => false;
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
    public List<string> Warnings { get; } = ["对照主线提供的独立reference并验证Core往返/数值映射；不是人工听辨或游戏验收，reference独立性由主线负责。",
        "语种来自manifest明确声明，空列表仍为未知；标题和歌手由主线官方索引提供，本工具不独立认证索引。",
        "POP909权利未核验，license=unverified，不授CC0，不发布。WAV为Core合成音色，不是原唱/游戏音色。"];
    public string? Failure { get; set; }
    public List<string> Failures { get; } = [];
}
internal static class Files
{
    public static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path, new UTF8Encoding(false, true)), JsonDefaults.Options)
        ?? throw new FormatException("JSON不能为null: " + path);
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
                Require((File.GetAttributes(p) & FileAttributes.ReparsePoint) == 0, "拒绝链接/重解析点: " + p);
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
    public static void SameSnapshot(string root, List<FileEvidence> before) => Require(before.SequenceEqual(Snapshot(root)), "输入目录变化: " + root);
}
