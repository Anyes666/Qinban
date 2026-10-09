using System.Text.RegularExpressions;
namespace QinBan.Core;

public static class SongMetadata
{
    // Identity fields are source declarations, not a certification of music, rights or reviews.
    public static bool HasRequiredIdentity(ScoreProvenance provenance) =>
        (provenance.Artists?.Any(artist => !string.IsNullOrWhiteSpace(artist)) == true || !string.IsNullOrWhiteSpace(provenance.Artist))
        && provenance.LanguageTags is { Count: > 0 } && provenance.LanguageTags.All(tag => IsLanguageTag(tag)
            && !tag.Split('-')[0].Equals("und", StringComparison.OrdinalIgnoreCase));

    public static string ArtistText(ScoreProvenance provenance) => provenance.Artists.Count > 0
        ? string.Join(" / ", provenance.Artists) : !string.IsNullOrWhiteSpace(provenance.Artist) ? provenance.Artist : "歌手未标注";

    public static string LanguageText(ScoreProvenance provenance) => provenance.LanguageTags.Count == 0 ? "语种未知"
        : string.Join(" / ", provenance.LanguageTags.Select(tag => tag.Split('-')[0].ToLowerInvariant() switch
        {
            "cmn" => "国语",
            "zh" => "中文（未细分）",
            "yue" => "粤语",
            "en" => "英语",
            "ja" => "日语",
            "ko" => "韩语",
            "zxx" => "纯音乐（无歌词）",
            "und" => "语种未知",
            _ => tag
        }));

    // Simple syntax only: 2–8 ASCII letters, then optional 1–8 ASCII alphanumeric subtags;
    // at most 256 characters. This does not certify BCP47 registry validity or infer language from a title.
    internal static bool IsLanguageTag(string? tag) => tag is { Length: > 0 and <= 256 }
        && Regex.IsMatch(tag, @"\A[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*\z", RegexOptions.CultureInvariant);
}
