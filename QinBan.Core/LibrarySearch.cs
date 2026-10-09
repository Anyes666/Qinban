using System.Globalization;
using System.Text;
namespace QinBan.Core;

public sealed record SearchKeys(string Title, string Author, string Text, string Pinyin, string Initials, string SortTitle);
public static class LibrarySearch
{
    private static readonly Lazy<Dictionary<int, string>> Readings = new(() => ReadTable("pinyin-17.tsv"));
    private static readonly Lazy<Dictionary<int, int>> Variants = new(() => ReadTable("simplified-17.tsv")
        .ToDictionary(p => p.Key, p => int.Parse(p.Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture)));
    private static Dictionary<int, string> ReadTable(string suffix)
    {
        var assembly = typeof(LibrarySearch).Assembly;
        string name = assembly.GetManifestResourceNames().Single(n => n.EndsWith(suffix, StringComparison.Ordinal));
        using var stream = assembly.GetManifestResourceStream(name)!; using var reader = new StreamReader(stream, Encoding.UTF8);
        var values = new Dictionary<int, string>();
        while (reader.ReadLine() is { } line)
        {
            if (line.StartsWith('#') || line.Length == 0) continue;
            string[] parts = line.Split('\t'); values.Add(int.Parse(parts[0], NumberStyles.HexNumber, CultureInfo.InvariantCulture), parts[1]);
        }
        return values;
    }
    public static string Normalize(string text)
    {
        var result = new StringBuilder(); bool space = false;
        foreach (var original in text.Normalize(NormalizationForm.FormKC).Normalize(NormalizationForm.FormD).EnumerateRunes())
        {
            var kind = Rune.GetUnicodeCategory(original);
            if (kind is UnicodeCategory.NonSpacingMark or UnicodeCategory.SpacingCombiningMark or UnicodeCategory.EnclosingMark) continue;
            Rune rune = Variants.Value.TryGetValue(original.Value, out int simple) ? new Rune(simple) : original;
            if (Rune.IsLetterOrDigit(rune)) { if (space && result.Length > 0) result.Append(' '); result.Append(Rune.ToLowerInvariant(rune)); space = false; }
            else space = true;
        }
        return result.ToString();
    }
    private static (string Full, string Initials) Phonetics(string text)
    {
        var full = new StringBuilder(); var initials = new StringBuilder(); bool wordStart = true;
        foreach (var rune in Normalize(text).EnumerateRunes())
        {
            if (Readings.Value.TryGetValue(rune.Value, out string? reading)) { full.Append(reading); initials.Append(reading[0]); wordStart = true; }
            else if (Rune.IsLetterOrDigit(rune)) { full.Append(rune); if (wordStart) initials.Append(rune); wordStart = false; }
            else wordStart = true;
        }
        return (full.ToString(), initials.ToString());
    }
    public static SearchKeys Build(LibraryEntry entry)
    {
        entry.Provenance.Validate();
        string title = Normalize(entry.Title), author = Normalize(string.Join(" ", new[] { entry.Author, entry.Provenance.Artist }.Concat(entry.Provenance.Artists)));
        var fields = new[] { entry.Title, entry.Author, entry.Provenance.Artist, entry.Category, entry.Provenance.Provider,
                SongMetadata.LanguageText(entry.Provenance), entry.Provenance.Album, entry.Provenance.VersionLabel }
            .Concat(entry.Provenance.Artists).Concat(entry.Provenance.LanguageTags)
            .Concat(entry.Provenance.Aliases).Concat(entry.Provenance.Tags).Where(s => !string.IsNullOrWhiteSpace(s)).ToArray();
        var phonetics = fields.Select(Phonetics).ToArray();
        return new(title, author, string.Join(" | ", fields.Select(Normalize)),
            string.Join(" | ", phonetics.Select(p => p.Full)), string.Join(" | ", phonetics.Select(p => p.Initials)), Phonetics(entry.Title).Full);
    }
    public static string[] Terms(string search)
    {
        if (search.Length > 512) throw new FormatException("搜索词不能超过 512 个字符。");
        var terms = Normalize(search).Split(' ', StringSplitOptions.RemoveEmptyEntries).Distinct().ToArray();
        if (terms.Length > 16) throw new FormatException("组合搜索最多 16 个不同词，请缩短搜索条件。");
        return terms;
    }
}
