using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using QinBan.Core;

internal sealed class ReferenceDocument
{
    public required List<NoteEvent> Notes { get; init; }
    public required double LengthMs { get; init; }
    public required double Bpm { get; init; }
    public required int TempoChanges { get; init; }
    public string Reference { get; init; } = "external reference supplied by main thread";
    public string? SourceSha256 { get; init; }
}
internal sealed record TimingEvidence(string ReferencePath, string ReferenceSha256, string ReferenceDescription,
    bool Passed, int Notes, int TempoChanges, double MaxOnsetErrorMs, double MaxDurationErrorMs,
    double LengthErrorMs, double BpmError, double ToleranceMs, double BpmTolerance);

internal static class PlanChecks
{
    public const double TimingToleranceMs = .002;
    public static TimingEvidence CompareReference(SongDocument song, string path, string sourceHash)
    {
        var reference = Files.Read<ReferenceDocument>(path);
        Files.Require(reference.Notes is { Count: > 0 } && reference.Notes.Count == song.Notes.Count, "reference note count不同");
        Files.Require(double.IsFinite(reference.LengthMs) && reference.LengthMs >= 0 && double.IsFinite(reference.Bpm)
            && reference.Bpm > 0 && reference.TempoChanges > 0, "reference length/bpm/tempoChanges不合法");
        if (reference.SourceSha256 != null) Files.Require(reference.SourceSha256.Equals(sourceHash, StringComparison.OrdinalIgnoreCase), "reference source SHA不匹配");
        List<NoteEvent> Sort(IEnumerable<NoteEvent> notes) => notes.OrderBy(n => n.Track).ThenBy(n => n.StartMs)
            .ThenBy(n => n.Pitch).ThenBy(n => n.DurationMs).ThenBy(n => n.Velocity).ToList();
        var actual = Sort(song.Notes); var expected = Sort(reference.Notes);
        double onset = 0, duration = 0;
        for (int i = 0; i < actual.Count; i++)
        {
            var a = actual[i]; var e = expected[i];
            Files.Require(a.Pitch == e.Pitch && a.Track == e.Track && a.Velocity == e.Velocity && a.Percussion == e.Percussion,
                $"reference音符身份不同，排序位置{i}: pitch/track/velocity/percussion");
            Files.Require(double.IsFinite(e.StartMs) && e.StartMs >= 0 && double.IsFinite(e.DurationMs) && e.DurationMs > 0, "reference音符时间非法");
            onset = Math.Max(onset, Math.Abs(a.StartMs - e.StartMs));
            duration = Math.Max(duration, Math.Abs(a.DurationMs - e.DurationMs));
        }
        double length = Math.Abs(song.LengthMs - reference.LengthMs), bpm = Math.Abs(song.Bpm - reference.Bpm);
        double bpmTolerance = Math.Max(.000001, reference.Bpm * .00000001);
        Files.Require(onset <= TimingToleranceMs && duration <= TimingToleranceMs && length <= TimingToleranceMs,
            $"reference时序超差: onset={onset:R}, duration={duration:R}, length={length:R}, 上限0.002ms");
        Files.Require(bpm <= bpmTolerance, $"reference BPM超差: {bpm:R}, 上限{bpmTolerance:R}");
        return new(path, Files.Hash(path), reference.Reference, true, actual.Count, reference.TempoChanges,
            onset, duration, length, bpm, TimingToleranceMs, bpmTolerance);
    }
    public static MappingEvidence Assess(string id, SongDocument song, InstrumentProfile profile, PlayOptions options,
        PlaybackPlan plan, bool sampled)
    {
        var selected = options.Tracks!.ToHashSet();
        var source = song.Notes.Where(n => selected.Contains(n.Track) && !n.Percussion).ToList();
        var onsets = source.GroupBy(n => n.StartMs).ToDictionary(g => g.Key, g => g.ToList());
        var keys = profile.Keys.ToDictionary(k => k.Key);
        bool Near(double a, double b) => Math.Abs(a - b) <= .000001;
        Files.Require(plan.Notes.Count > 0 && plan.Report.Original == song.Notes.Count && plan.Report.Output == plan.Notes.Count, "计划为空或统计错误: " + id + "/" + profile.Id);
        Files.Require(plan.Notes.SequenceEqual(plan.Notes.OrderBy(n => n.StartMs).ThenBy(n => n.Pitch)), "计划时序未排序");
        Files.Require(plan.Notes.Select(n => (n.Key, n.StartMs)).Distinct().Count() == plan.Notes.Count, "同拍同键重复");
        Files.Require(new[] { plan.Report.Folded, plan.Report.Accidentals, plan.Report.Skipped, plan.Report.Simplified,
            plan.Report.DuplicateKeys, plan.Report.NativeChords }.All(n => n >= 0), "负的映射统计");
        int shortened = 0;
        var releaseLimits = new Dictionary<(char Key, double Start), double>();
        foreach (var group in plan.Notes.GroupBy(n => n.Key))
        {
            var notes = group.OrderBy(n => n.StartMs).ToArray();
            for (int i = 0; i < notes.Length - 1; i++)
            {
                double gap = notes[i + 1].StartMs - notes[i].StartMs;
                releaseLimits[(notes[i].Key, notes[i].StartMs)] = Math.Max(.1, gap - Math.Min(8, gap / 4));
            }
        }
        foreach (var n in plan.Notes)
        {
            Files.Require(double.IsFinite(n.StartMs) && n.StartMs >= 0 && double.IsFinite(n.HoldMs) && n.HoldMs > 0
                && double.IsFinite(n.SoundMs) && n.SoundMs > 0 && n.Velocity is >= 1 and <= 127, "非法计划时序/力度");
            Files.Require(keys.TryGetValue(n.Key, out var key) && n.Pitch == key.Pitches[0] && (key.IsChord
                ? n.ChordPitches != null && n.ChordPitches.SequenceEqual(key.Pitches) : n.ChordPitches == null), "非法键位/音域/和弦");
            Files.Require(n.Sustain == profile.SupportsSustain && selected.Contains(n.Track), "计划延音/轨道错误");
            Files.Require(onsets.TryGetValue(n.StartMs, out var group), "起音不来自选中源轨道");
            double limit = releaseLimits.GetValueOrDefault((n.Key, n.StartMs), double.PositiveInfinity);
            double[] durations = key!.IsChord ? [group!.Min(s => s.DurationMs)]
                : group!.Where(s => s.Track == n.Track && s.Velocity == n.Velocity).Select(s => s.DurationMs).ToArray();
            Files.Require(durations.Any(d => Near(n.SoundMs, n.Sustain ? Math.Min(d, limit) : d)
                && Near(n.HoldMs, Math.Min(n.Sustain && options.HoldByScore ? d : options.HoldMs, limit))), "音长/触键不符合源时长或同键释放规则");
            if (n.Sustain && durations.Any(d => d > n.SoundMs + .000001)) shortened++;
            if (key.IsChord) Files.Require(group.Select(s => ((s.Pitch + options.Transpose + options.Octave * 12) % 12 + 12) % 12).Distinct().Order()
                .SequenceEqual(key.Pitches.Select(p => p % 12).Distinct().Order()), "凭空生成原生和弦");
        }
        Files.Require(Near(plan.DurationMs, Math.Max(song.DurationMs, plan.Notes.Max(n => n.StartMs + n.HoldMs))), "源尾休止/计划总长不保留");
        Files.Require(plan.Notes.Count(n => n.ChordPitches != null) == plan.Report.NativeChords, "原生和弦统计不一致");
        return new(id, profile.Id, sampled, true, song.Notes.Count, source.Count,
            song.Notes.Count(n => !selected.Contains(n.Track)), song.Notes.Count(n => selected.Contains(n.Track) && n.Percussion),
            plan.Report, shortened, plan.Warnings);
    }
    public static WaveEvidence RenderFragment(string id, string instrument, PlaybackPlan full, string output)
    {
        // The API itself adds 450ms; subtract this from the plan cap to keep actual WAV <=30 seconds.
        double end = Math.Min(29550, full.DurationMs);
        double start = 0;
        if (!full.Notes.Any(n => n.StartMs < end))
        {
            start = full.Notes.Min(n => n.StartMs);
            end = Math.Min(start + 29550, full.DurationMs);
        }
        var notes = full.Notes.Where(n => n.StartMs >= start && n.StartMs < end).Select(n => n with {
            StartMs = n.StartMs - start, HoldMs = Math.Min(n.HoldMs, end - n.StartMs), SoundMs = Math.Min(n.SoundMs, end - n.StartMs)
        }).ToList();
        var fragment = new PlaybackPlan(notes, end - start, full.Report, ["最多30秒片段，仅合成音色；未自动播放。"]);
        string relative = Path.Combine("wav", $"pop909-{id}.{instrument}.fragment-max30s.wav");
        string path = Path.Combine(output, relative);
        double rendered = PreviewAudio.WriteWave(fragment, path);
        using var stream = File.OpenRead(path); using var reader = new BinaryReader(stream);
        byte[] h = reader.ReadBytes(44);
        Files.Require(h.Length == 44 && Encoding.ASCII.GetString(h, 0, 4) == "RIFF"
            && Encoding.ASCII.GetString(h, 8, 8) == "WAVEfmt " && Encoding.ASCII.GetString(h, 36, 4) == "data"
            && BinaryPrimitives.ReadInt16LittleEndian(h.AsSpan(20)) == 1
            && BinaryPrimitives.ReadInt16LittleEndian(h.AsSpan(22)) == 1
            && BinaryPrimitives.ReadInt32LittleEndian(h.AsSpan(24)) == PreviewAudio.SampleRate
            && BinaryPrimitives.ReadInt16LittleEndian(h.AsSpan(34)) == 16, "WAV头无效");
        int bytes = BinaryPrimitives.ReadInt32LittleEndian(h.AsSpan(40));
        Files.Require(stream.Length == 44L + bytes && BinaryPrimitives.ReadInt32LittleEndian(h.AsSpan(4)) == bytes + 36, "WAV文件长度不一致");
        double actualMs = bytes / 2.0 / PreviewAudio.SampleRate * 1000;
        Files.Require(actualMs <= 30000 + 1000.0 / PreviewAudio.SampleRate && Math.Abs(actualMs - rendered) <= 1000.0 / PreviewAudio.SampleRate, "WAV超过30秒或时长不一致");
        return new(id, instrument, relative, Files.Hash(path), start, end, actualMs, notes.Count, true,
            "最多30秒的截取合成音色片段（含450ms释放尾音），不是全曲或原唱/游戏采样；不改完整计划/源谱。");
    }
}
