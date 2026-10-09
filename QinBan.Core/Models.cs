using System.Text.Json;
using System.Text.Json.Serialization;

namespace QinBan.Core;

public sealed record NoteEvent(int Pitch, double StartMs, double DurationMs, int Track = 0, int Velocity = 90, bool Percussion = false);
public sealed record TrackInfo(int Id, string Name, int NoteCount, bool Percussion);

public sealed class SongDocument
{
    public int Version { get; set; } = 1;
    public string Title { get; set; } = "未命名谱子";
    public string Author { get; set; } = "未知";
    public string Category { get; set; } = "我的谱子";
    public string Source { get; set; } = "本地导入";
    public string Description { get; set; } = "";
    public ScoreProvenance Provenance { get; set; } = new();
    public string KeyInstrumentId { get; set; } = "windsong";
    public double Bpm { get; set; } = 100;
    public double LengthMs { get; set; }
    public List<NoteEvent> Notes { get; set; } = [];
    [JsonIgnore] public double DurationMs => Math.Max(LengthMs, Notes.Count == 0 ? 0 : Notes.Max(n => n.StartMs + n.DurationMs));
    public List<string> Warnings { get; set; } = [];
    [JsonIgnore] public List<TrackInfo> Tracks => Notes.GroupBy(n => n.Track).OrderBy(g => g.Key)
        .Select(g => new TrackInfo(g.Key, $"轨道 {g.Key + 1}{(g.All(n => n.Percussion) ? " · 打击乐" : "")}", g.Count(), g.All(n => n.Percussion))).ToList();
    public SongDocument Copy() => JsonSerializer.Deserialize<SongDocument>(JsonSerializer.Serialize(this, JsonDefaults.Options), JsonDefaults.Options)!;
}

public enum AccidentalMode { Nearest, Lower, Upper, Skip }
public enum RangeMode { FoldOctaves, Skip }
public enum ChordMode { Simultaneous, Ascending, Descending, MelodyOnly }

public sealed class PlayOptions
{
    public string InstrumentId { get; set; } = "windsong";
    public bool HoldByScore { get; set; } = true;
    public bool NativeGuitarChords { get; set; } = true;
    public double Speed { get; set; } = 1;
    public int Transpose { get; set; }
    public int Octave { get; set; }
    public AccidentalMode Accidentals { get; set; } = AccidentalMode.Nearest;
    public RangeMode Range { get; set; } = RangeMode.FoldOctaves;
    public ChordMode Chords { get; set; } = ChordMode.Simultaneous;
    public int MaxChordNotes { get; set; } = 5;
    public int StrumMs { get; set; } = 35;
    public int HoldMs { get; set; } = 65;
    // Kept only for old library.json compatibility; no countdown is used.
    public int CountdownSeconds { get; set; } = 5;
    public bool ExcludePercussion { get; set; } = true;
    // Missing legacy setting inherits the POP909 default; an explicit false is remembered.
    public bool? SmartInterludes { get; set; }
    public List<int>? Tracks { get; set; }
    public bool Loop { get; set; }
    public double LoopStartMs { get; set; }
    public double LoopEndMs { get; set; }
    public PlayOptions Copy() => JsonSerializer.Deserialize<PlayOptions>(JsonSerializer.Serialize(this, JsonDefaults.Options), JsonDefaults.Options)!;
    public void Validate()
    {
        if (!double.IsFinite(Speed) || Speed < .25 || Speed > 3) throw new FormatException("速度必须在 0.25–3.00 倍之间。");
        if (Transpose is < -24 or > 24 || Octave is < -2 or > 2) throw new FormatException("移调超出支持范围。");
        if (MaxChordNotes is < 1 or > 10 || StrumMs is < 0 or > 150 || HoldMs is < 20 or > 250) throw new FormatException("和弦或按键时长参数超出范围。");
        _ = InstrumentCatalog.Get(InstrumentId);
        if (!Enum.IsDefined(Accidentals) || !Enum.IsDefined(Range) || !Enum.IsDefined(Chords)) throw new FormatException("不支持的演奏模式。");
        if (!double.IsFinite(LoopStartMs) || !double.IsFinite(LoopEndMs) || LoopStartMs < 0 || LoopEndMs < 0) throw new FormatException("循环时间无效。");
    }
}

public sealed record PlannedNote(int Pitch, char Key, double StartMs, double HoldMs, double SoundMs, int Velocity, int Track, IReadOnlyList<int>? ChordPitches = null, bool Sustain = false);
public sealed record ConversionReport(int Original, int Output, int Folded, int Accidentals, int Skipped, int Simplified, int DuplicateKeys, int NativeChords = 0, int InterludeNotes = 0, int InterludeSegments = 0)
{
    public string Summary => $"原谱 {Original} 音 → 演奏 {Output} 音 · 八度折叠 {Folded} · 半音替换 {Accidentals} · 省略 {Skipped + Simplified + DuplicateKeys}" + (NativeChords > 0 ? $" · 原生和弦 {NativeChords} 组" : "") + (InterludeNotes > 0 ? $" · 智能接续 {InterludeNotes} 源音 / {InterludeSegments} 段" : "");
}
public sealed record PlaybackPlan(List<PlannedNote> Notes, double DurationMs, ConversionReport Report, List<string> Warnings);

public sealed class LibraryEntry
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Title { get; set; } = "";
    public string Author { get; set; } = "";
    public string Category { get; set; } = "";
    public string RelativePath { get; set; } = "";
    public string Hash { get; set; } = "";
    public string ResourceHash { get; set; } = "";
    public string CatalogId { get; set; } = "";
    public ScoreProvenance Provenance { get; set; } = new();
    public bool BuiltIn { get; set; }
    public bool Favorite { get; set; }
    public bool InQueue { get; set; }
    public double DurationMs { get; set; }
    public int NotesCount { get; set; }
    public double Bpm { get; set; }
    public DateTimeOffset AddedAt { get; set; } = DateTimeOffset.Now;
    public DateTimeOffset? LastPlayedAt { get; set; }
    public PlayOptions Options { get; set; } = new();
    [JsonIgnore] public string DurationText => TimeSpan.FromMilliseconds(DurationMs).ToString(@"mm\:ss");
    [JsonIgnore] public string Detail => $"{Author}  ·  {Category}  ·  {Bpm:0} BPM";
    [JsonIgnore] public string ArtistText => SongMetadata.ArtistText(Provenance);
    [JsonIgnore] public string LanguageText => SongMetadata.LanguageText(Provenance);
    [JsonIgnore] public string MetadataText => $"{ArtistText} · {LanguageText}"
        + (string.IsNullOrWhiteSpace(Provenance.VersionLabel) ? "" : $" · {Provenance.VersionLabel}");
    [JsonIgnore] public string MetadataTooltip => MetadataText + $"\n作者 / 编谱者：{Author}\n专辑："
        + (string.IsNullOrWhiteSpace(Provenance.Album) ? "未标注" : Provenance.Album) + $"\n分类：{Category}";
    [JsonIgnore] public string QualityText => BuiltIn ? Provenance.StatusText : "个人谱 · 来源/审核声明未认证";
    [JsonIgnore] public string FavoriteText => Favorite ? "已收藏" : "收藏";
    [JsonIgnore] public string QueueText => InQueue ? "移出队列" : "加入队列";
}

public static class JsonDefaults
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true, MaxDepth = 32, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        Converters = { new JsonStringEnumConverter() }
    };
}
