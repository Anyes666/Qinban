using System.Text.Json.Serialization;
namespace QinBan.Core;

public sealed class ScoreProvenance
{
    public string WorkId { get; set; } = "";
    public string EditionId { get; set; } = "";
    public string Artist { get; set; } = "";
    public List<string> Artists { get; set; } = [];
    public List<string> LanguageTags { get; set; } = [];
    public string Album { get; set; } = "";
    public string VersionLabel { get; set; } = "";
    public string Provider { get; set; } = "local";
    public List<string> Aliases { get; set; } = [];
    public List<string> Tags { get; set; } = [];
    public string SourceUrl { get; set; } = "";
    public string License { get; set; } = "unverified";
    public string LicenseUrl { get; set; } = "";
    public string RightsStatus { get; set; } = "";
    public string SourceSha256 { get; set; } = "";
    public string NotationSha256 { get; set; } = "";
    public string Maintainer { get; set; } = "";
    public DateTimeOffset? RetrievedAt { get; set; }
    public string Completeness { get; set; } = "unknown";
    public string TimingStatus { get; set; } = "unverified";
    public string MusicReview { get; set; } = "not-reviewed";
    public string GameReview { get; set; } = "not-tested";
    public bool Synthetic { get; set; }
    // Source timing, music correctness and redistribution are deliberately separate.
    public bool RedistributionVerified { get; set; }
    [JsonIgnore] public bool IsFormalSong => !Synthetic && RedistributionVerified && Completeness == "full-work"
        && TimingStatus == "source-compared" && MusicReview == "human-reviewed" && GameReview == "verified-arrangement"
        && SongMetadata.HasRequiredIdentity(this);
    [JsonIgnore] public string StatusText => Synthetic ? "合成压力数据" : TimingStatus == "source-compared" && MusicReview != "human-reviewed" ? "来源时序校验 · 未人工精校"
        : MusicReview == "human-reviewed" ? "人工精校" : Completeness == "exercise" ? "教学 / 练习" : "个人谱 · 待核验";
    public void Validate()
    {
        if (Artists == null || Artists.Count > 32 || Artists.Any(s => string.IsNullOrWhiteSpace(s) || s.Length > 256)
            || Artists.Select(s => s.Trim()).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Artists.Count)
            throw new FormatException("歌手须为非 null 列表，最多 32 项；每项须非空且不超过 256 字，不允许重复。");
        if (LanguageTags == null || LanguageTags.Count > 16 || LanguageTags.Any(s => !SongMetadata.IsLanguageTag(s))
            || LanguageTags.Distinct(StringComparer.OrdinalIgnoreCase).Count() != LanguageTags.Count)
            throw new FormatException("语种须为非 null 列表，最多 16 个不重复的简单语言标签；仅校验语法，不认证 BCP47 注册有效性。");
        if (Album == null || Album.Length > 1000 || VersionLabel == null || VersionLabel.Length > 256)
            throw new FormatException("专辑/版本标签不能为 null，长度分别不超过 1000/256 字。");
        if (RightsStatus == null || RightsStatus.Length > 64 || (RightsStatus.Length > 0
            && (!char.IsAsciiLetterOrDigit(RightsStatus[0]) || RightsStatus.Skip(1).Any(c =>
                !char.IsAsciiLetterOrDigit(c) && c is not ('.' or '_' or '-')))))
            throw new FormatException("rights status must be empty or a stable 1-64 character token.");
        if (Aliases == null || Tags == null || Aliases.Count > 100 || Tags.Count > 100) throw new FormatException("别名/标签须为有效列表且各不超过 100 项。");
        var values = new[] { WorkId, EditionId, Artist, Provider, SourceUrl, License, LicenseUrl, SourceSha256, NotationSha256, Maintainer, Completeness, TimingStatus, MusicReview, GameReview };
        if (values.Any(s => s == null || s.Length > 4096) || Aliases.Concat(Tags).Any(s => s == null || s.Length > 256)) throw new FormatException("来源/搜索元数据超出允许长度。");
    }
}

public enum LibraryFilter { All, Personal, BuiltIn, Recent, Samples, ChinesePop, ChinesePopular, UnknownLanguage }
public enum LibrarySort { Added, Title, Duration, Recent, ChinesePopular }
public enum LibraryQuality { All, TimingCompared, NotHumanReviewed, Exercises }
public sealed record LibraryQuery(string Search = "", LibraryFilter Filter = LibraryFilter.All,
    LibrarySort Sort = LibrarySort.Added, bool Favorites = false, bool Queue = false,
    string? PlaylistId = null, LibraryQuality Quality = LibraryQuality.All, int Offset = 0, int Limit = 50, string? WorkId = null);
public sealed record LibraryPage(IReadOnlyList<LibraryEntry> Items, int Total, int LibraryTotal, int Offset, int Limit);
public sealed record PlaylistInfo(string Id, string Name, int Count);
public sealed record LibraryStatistics(int Scores, int Works, int Samples, int FormalSongs, int UserScores);

// Language counts are derived from explicit metadata only. Missing language tags are not treated as English.
public sealed record LibraryLanguageSummary(int ChinesePop, int ChinesePopular, int ExplicitEnglish, int UnknownLanguage, int Total);
