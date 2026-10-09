using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Melanchall.DryWetMidi.Core;
using Melanchall.DryWetMidi.Interaction;
using Midi = Melanchall.DryWetMidi.Core.MidiFile;

namespace QinBan.Core;

public static class SongParser
{
    public const int MaxNotes = 100_000;
    public const long MaxFileBytes = 16 * 1024 * 1024;
    public const double MaxDurationMs = 30 * 60 * 1000;
    public static SongDocument Read(string path)
    {
        var info = new FileInfo(path);
        if (!info.Exists) throw new FileNotFoundException("谱子文件不存在。", path);
        if (info.Length > MaxFileBytes) throw new FormatException("单个谱子不能超过 16 MB。");
        var extension = info.Extension.ToLowerInvariant();
        SongDocument song;
        if (extension is ".mid" or ".midi") song = ReadMidi(path);
        else
        {
            string text = ReadText(path, out bool legacy);
            song = extension switch
            {
                ".txt" => ParseText(text, Path.GetFileNameWithoutExtension(path)),
                ".json" => ParseJson(text),
                _ => throw new FormatException("仅支持 .mid、.midi、.txt 和 .json；PDF/图片/音频不是可直接演奏的谱子。")
            };
            if (legacy) song.Warnings.Add("原文件不是 UTF-8，已按 GB18030 解码；请检查中文标题。");
        }
        Validate(song);
        return song;
    }
    private static string ReadText(string path, out bool legacy)
    {
        legacy = false;
        try { using var reader = new StreamReader(path, new UTF8Encoding(false, true), true); return reader.ReadToEnd(); }
        catch (DecoderFallbackException)
        {
            legacy = true;
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            return File.ReadAllText(path, Encoding.GetEncoding(54936, EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback));
        }
    }
    public static SongDocument ReadMidi(string path)
    {
        // Preserve the ORIGINAL full-file tempo map, as in the upstream MIDI model;
        // filtering a melody track must not lose tempo changes located in a different track.
        var midi = Midi.Read(path, new ReadingSettings { TextEncoding = Encoding.UTF8, EndOfTrackStoringPolicy = EndOfTrackStoringPolicy.Store });
        var tempo = midi.GetTempoMap();
        var song = new SongDocument { Title = Path.GetFileNameWithoutExtension(path), Bpm = tempo.GetTempoAtTime(new MidiTimeSpan(0)).BeatsPerMinute, Category = "MIDI 导入", Source = "本地 MIDI，保留原文件" };
        int track = 0;
        foreach (var chunk in midi.GetTrackChunks())
        {
            foreach (var note in chunk.GetNotes())
            {
                double start = note.TimeAs<MetricTimeSpan>(tempo).TotalMicroseconds / 1000.0;
                double end = TimeConverter.ConvertTo<MetricTimeSpan>(note.Time + note.Length, tempo).TotalMicroseconds / 1000.0;
                song.Notes.Add(new((int)note.NoteNumber, start, end - start, track, (int)note.Velocity, note.Channel == 9));
                if (song.Notes.Count > MaxNotes) throw new FormatException("MIDI 超过 100,000 个音符，请先精简轨道。");
            }
            track++;
        }
        // Retain source terminal rests: reading defaults omit EndOfTrack, so explicitly store it and include its tick.
        long endTick = midi.GetTrackChunks().Select(c => c.Events.Sum(e => e.DeltaTime)).DefaultIfEmpty(0).Max();
        song.LengthMs = TimeConverter.ConvertTo<MetricTimeSpan>(endTick, tempo).TotalMicroseconds / 1000.0;
        song.Notes = song.Notes.OrderBy(n => n.StartMs).ThenBy(n => n.Pitch).ToList();
        if (song.Notes.Any(n => n.Percussion)) song.Warnings.Add("包含 MIDI 第 10 通道打击乐，演奏时默认排除；原始音符仍被保留。");
        Validate(song); return song;
    }
    public static SongDocument ParseJson(string text)
    {
        using var json = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 32 });
        var root = json.RootElement;
        if (root.ValueKind == JsonValueKind.Array)
        {
            if (root.GetArrayLength() != 1) throw new FormatException("一个 JSON 文件包含多首歌，请先拆分为每首一个文件。");
            root = root[0];
        }
        if (root.ValueKind != JsonValueKind.Object) throw new FormatException("JSON 顶层必须是谱子对象。");
        SongDocument song;
        if (TryProp(root, "songNotes", out var keyNotes))
        {
            song = new() { Title = StringProp(root, "name", "导入键位谱"), Author = StringProp(root, "author", "未知"), Category = "JSON 键位谱", KeyInstrumentId = StringProp(root, "keyInstrumentId", "windsong"), Bpm = TryProp(root, "bpm", out var bpm) ? bpm.GetDouble() : 100 };
            if (TryProp(root, "provenance", out var provenance))
                song.Provenance = JsonSerializer.Deserialize<ScoreProvenance>(provenance.GetRawText(), JsonDefaults.Options) ?? throw new FormatException("来源信息不能为空。");
            if (keyNotes.ValueKind != JsonValueKind.Array || keyNotes.GetArrayLength() > MaxNotes) throw new FormatException("songNotes 必须是数组且不超过 100,000 音。");
            var keyInstrument = InstrumentCatalog.Get(song.KeyInstrumentId);
            if (!keyInstrument.CanAutoPlay) throw new FormatException("此来源乐器键位待核验，暂不解读键位谱。");
            bool fallbackDuration = false;
            foreach (var item in keyNotes.EnumerateArray())
            {
                string key = Required(item, "key").GetString() ?? "";
                var match = Regex.Match(key, @"^(?:\d+)?Key(\d+)$", RegexOptions.IgnoreCase);
                if (!match.Success || !int.TryParse(match.Groups[1].Value, out int index) || index < 0 || index >= keyInstrument.Keys.Count) throw new FormatException($"无法识别键位索引 {key}；来源乐器 {keyInstrument.Name} 共有 {keyInstrument.Keys.Count} 键。");
                double time = Required(item, "time").GetDouble();
                double duration = TryProp(item, "durationMs", out var length) ? length.GetDouble() : 200;
                fallbackDuration |= !TryProp(item, "durationMs", out _);
                foreach (int pitch in keyInstrument.Keys[index].Pitches) song.Notes.Add(new(pitch, time, duration));
                if (song.Notes.Count > MaxNotes) throw new FormatException("展开乐器和弦后超过 100,000 个音符。");
            }
            song.Warnings.Add($"songNotes 按来源乐器 {keyInstrument.Name} 的 {keyInstrument.Keys.Count} 键索引解读；缺少 keyInstrumentId 时默认风物之诗琴，并非任意游戏通用索引。");
            if (fallbackDuration) song.Warnings.Add("部分 songNotes 没有 durationMs：保留 time 的不等间隔起音与休止，但这些音长暂用 200ms，不能据此自动还原长音。");
            song.Description = "键位 JSON 导入。索引映射须人工确认；源文件保留。";
        }
        else
        {
            var notes = Required(root, "notes");
            if (notes.ValueKind != JsonValueKind.Array || notes.GetArrayLength() > MaxNotes) throw new FormatException("notes 必须是数组且不超过 100,000 音。");
            foreach (var note in notes.EnumerateArray())
            {
                Required(note, "pitch"); Required(note, "startMs"); Required(note, "durationMs");
            }
            song = JsonSerializer.Deserialize<SongDocument>(root.GetRawText(), JsonDefaults.Options) ?? throw new FormatException("无法读取 JSON 谱子。");
        }
        Validate(song); return song;
    }
    private static bool TryProp(JsonElement element, string name, out JsonElement result)
    {
        if (element.ValueKind == JsonValueKind.Object)
            foreach (var property in element.EnumerateObject()) if (property.Name.Equals(name, StringComparison.OrdinalIgnoreCase)) { result = property.Value; return true; }
        result = default; return false;
    }
    private static JsonElement Required(JsonElement element, string name) => TryProp(element, name, out var value) ? value : throw new FormatException($"JSON 缺少字段：{name}");
    private static string StringProp(JsonElement element, string name, string fallback) => TryProp(element, name, out var value) ? value.GetString() ?? fallback : fallback;

    public static SongDocument ParseText(string text, string defaultTitle = "新建谱子")
    {
        if (Encoding.UTF8.GetByteCount(text) > MaxFileBytes) throw new FormatException("文本谱过大。");
        var song = new SongDocument { Title = defaultTitle, Category = "文本谱", Source = "自编或本地文本谱" };
        string format = "";
        var lines = new List<string>();
        foreach (string raw in text.Replace("\r", "").Split('\n'))
        {
            string line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("//") || (line.StartsWith('#') && !Regex.IsMatch(line, @"^#[1-7]"))) continue;
            int equals = line.IndexOf('=');
            if (equals > 0)
            {
                string key = line[..equals].Trim().ToUpperInvariant(), value = line[(equals + 1)..].Trim();
                switch (key)
                {
                    case "TITLE": song.Title = value; break;
                    case "AUTHOR": song.Author = value; break;
                    case "ARTISTS": song.Provenance.Artists = value.Length == 0 ? [] : value.Split('|').Select(item => item.Trim()).ToList(); break;
                    case "LANGUAGES": song.Provenance.LanguageTags = value.Length == 0 ? [] : value.Split('|').Select(item => item.Trim()).ToList(); break;
                    case "ALBUM": song.Provenance.Album = value; break;
                    case "EDITION": song.Provenance.VersionLabel = value; break;
                    case "BPM": song.Bpm = ParseNumber(value); break;
                    case "FORMAT": format = value.ToLowerInvariant(); break;
                    case "INSTRUMENT": song.KeyInstrumentId = value.ToLowerInvariant(); break;
                    default: throw new FormatException($"未知谱头字段：{key}");
                }
            }
            else lines.Add(line);
        }
        string body = string.Join(" ", lines);
        if (format.Length == 0) format = Regex.IsMatch(Regex.Replace(body, @":[^\s|]+", ""), "[1-7]") ? "numbered" : "keys";
        if (format is not ("keys" or "numbered")) throw new FormatException("FORMAT 必须是 keys（键位）或 numbered（数字简谱）。");
        if (!double.IsFinite(song.Bpm) || song.Bpm is < 20 or > 400) throw new FormatException("BPM 必须为 20–400。");
        var textInstrument = InstrumentCatalog.Get(song.KeyInstrumentId);
        if (format == "keys" && !textInstrument.CanAutoPlay) throw new FormatException("此来源乐器键位待核验，暂不解读键位谱。");
        double position = 0, beat = 60000.0 / song.Bpm;
        foreach (Match match in Regex.Matches(body, @"\([^)]*\)(?::[^\s|]+)?|\[[^\]]*\](?::[^\s|]+)?|[^\s|]+"))
        {
            string token = match.Value;
            int colon = token.LastIndexOf(':');
            double beats = colon < 0 ? 1 : ParseNumber(token[(colon + 1)..]);
            if (colon >= 0) token = token[..colon];
            if (!double.IsFinite(beats) || beats is < .0625 or > 32) throw new FormatException($"时值必须为 1/16–32 拍：{match.Value}");
            bool chord = token.StartsWith('(') && token.EndsWith(')') || token.StartsWith('[') && token.EndsWith(']');
            string content = chord ? Regex.Replace(token[1..^1], @"\s", "") : token;
            if (content.Length == 0) throw new FormatException("空和弦无效。");
            var atoms = format == "keys" ? content.ToUpperInvariant().Select(c => c.ToString()).ToList() : ParseNumberedAtoms(content);
            if (chord && atoms.Any(a => a is "0" or "-" or ".")) throw new FormatException("和弦中不能包含休止符。");
            if (chord)
            {
                foreach (string atom in atoms) Add(atom, position, beats * beat);
                position += beats * beat;
            }
            else foreach (string atom in atoms) { Add(atom, position, beats * beat); position += beats * beat; }
            if (position > MaxDurationMs) throw new FormatException("谱子不能超过 30 分钟。");
        }
        void Add(string atom, double start, double duration)
        {
            if (atom is "0" or "-" or ".") return;
            int pitch;
            if (format == "keys")
            {
                var key = textInstrument.Keys.FirstOrDefault(k => k.Key == atom[0]) ?? throw new FormatException($"{textInstrument.Name} 不含按键 {atom}");
                foreach (int tone in key.Pitches) song.Notes.Add(new(tone, start, duration));
                if (song.Notes.Count > MaxNotes) throw new FormatException("谱子超过 100,000 音。");
                return;
            }
            else
            {
                var parsed = Regex.Match(atom, @"^([#b]?)([1-7])([',]*)$");
                if (!parsed.Success) throw new FormatException($"无法识别简谱：{atom}");
                int number = parsed.Groups[2].Value[0] - '1';
                pitch = 60 + new[] { 0, 2, 4, 5, 7, 9, 11 }[number] + (parsed.Groups[1].Value == "#" ? 1 : parsed.Groups[1].Value == "b" ? -1 : 0);
                pitch += (parsed.Groups[3].Value.Count(c => c == '\'') - parsed.Groups[3].Value.Count(c => c == ',')) * 12;
            }
            song.Notes.Add(new(pitch, start, duration));
            if (song.Notes.Count > MaxNotes) throw new FormatException("谱子超过 100,000 音。");
        }
        song.LengthMs = position;
        Validate(song); return song;
    }
    private static List<string> ParseNumberedAtoms(string content)
    {
        var matches = Regex.Matches(content, @"[#b]?[1-7][',]*|[0.\-]");
        if (string.Concat(matches.Select(m => m.Value)) != content) throw new FormatException($"无法识别数字简谱：{content}");
        return matches.Select(m => m.Value).ToList();
    }
    private static double ParseNumber(string value) => double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double result) ? result : throw new FormatException($"无效数字：{value}");

    public static void Validate(SongDocument song)
    {
        if (song.Provenance == null) throw new FormatException("来源元数据不能为 null。");
        song.Provenance.Validate();
        _ = InstrumentCatalog.Get(song.KeyInstrumentId);
        if (!double.IsFinite(song.LengthMs) || song.LengthMs is < 0 or > MaxDurationMs) throw new FormatException("谱子总时长无效。");
        if (song.Warnings == null || song.Warnings.Count > 100 || song.Warnings.Any(w => w == null || w.Length > 3000)) throw new FormatException("谱子警告字段无效。");
        if (song.Version != 1) throw new FormatException("不支持此谱子版本；当前支持 version=1。");
        if (string.IsNullOrWhiteSpace(song.Title) || song.Title.Length > 180) throw new FormatException("曲名必须为 1–180 字。");
        if (song.Author == null || song.Author.Length > 180 || song.Category == null || song.Category.Length > 80 || song.Description == null || song.Description.Length > 8000 || song.Source == null || song.Source.Length > 1000) throw new FormatException("谱子元数据长度无效。");
        if (!double.IsFinite(song.Bpm) || song.Bpm is < 20 or > 400) throw new FormatException("BPM 必须在 20–400 之间。");
        if (song.Notes == null || song.Notes.Count is < 1 or > MaxNotes) throw new FormatException("谱子须有 1–100,000 个音符，不能只有休止符。");
        foreach (var n in song.Notes)
        {
            if (n == null || n.Pitch is < 0 or > 127 || n.Velocity is < 1 or > 127 || n.Track is < 0 or > 1023 || !double.IsFinite(n.StartMs) || !double.IsFinite(n.DurationMs) || n.StartMs < 0 || n.DurationMs is <= 0 or > 60000 || n.StartMs + n.DurationMs > MaxDurationMs)
                throw new FormatException("音符无效：pitch 0–127、velocity 1–127、startMs ≥ 0、durationMs 0–60000，总时长不超过 30 分钟。");
        }
    }
    public static string ToJson(SongDocument song, bool indented = true) { Validate(song); return JsonSerializer.Serialize(song, new JsonSerializerOptions(JsonDefaults.Options) { WriteIndented = indented }); }
    public static void WriteMidi(SongDocument song, string path)
    {
        Validate(song);
        var tempo = TempoMap.Create(Tempo.FromBeatsPerMinute(song.Bpm));
        Melanchall.DryWetMidi.Interaction.Note ConvertNote(NoteEvent n) => new Melanchall.DryWetMidi.Interaction.Note((Melanchall.DryWetMidi.Common.SevenBitNumber)n.Pitch)
        {
            Time = TimeConverter.ConvertFrom(new MetricTimeSpan((long)(n.StartMs * 1000)), tempo),
            Length = LengthConverter.ConvertFrom(new MetricTimeSpan((long)(n.DurationMs * 1000)), TimeConverter.ConvertFrom(new MetricTimeSpan((long)(n.StartMs * 1000)), tempo), tempo),
            Velocity = (Melanchall.DryWetMidi.Common.SevenBitNumber)n.Velocity,
            Channel = (Melanchall.DryWetMidi.Common.FourBitNumber)(n.Percussion ? 9 : 0)
        };
        var chunks = song.Notes.GroupBy(n => n.Track).OrderBy(g => g.Key).Select(g => g.Select(ConvertNote).ToTrackChunk()).ToList();
        long endTime = TimeConverter.ConvertFrom(new MetricTimeSpan((long)(song.DurationMs * 1000)), tempo);
        foreach (var chunk in chunks)
        {
            foreach (var last in chunk.Events.OfType<EndOfTrackEvent>().ToList()) chunk.Events.Remove(last);
            long current = chunk.Events.Sum(e => e.DeltaTime);
            chunk.Events.Add(new TextEvent("QinBan: normalized score end") { DeltaTime = Math.Max(0, endTime - current) });
        }
        var midi = new Midi(chunks); midi.ReplaceTempoMap(tempo); midi.Write(path, overwriteFile: false);
    }
}
