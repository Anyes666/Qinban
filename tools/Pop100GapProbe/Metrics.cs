using QinBan.Core;

internal sealed record Span(double StartMs, double EndMs) { public double DurationMs => EndMs - StartMs; }
internal sealed record GapStats(int CountGe5s, double TotalGe5sMs, double MaximumInternalMs,
    double LeadingMs, double TrailingMs, double ActiveMs, List<Span> GapsGe5s);
internal sealed record OnsetStats(int DistinctOnsets, int CountGe5s, double TotalGe5sMs,
    double MaximumGapMs, double FirstOnsetMs, double LastOnsetMs, List<Span> GapsGe5s);
internal sealed record Density(int MaxExactOnsetKeys, int MaxExactOnsetVoices, int MaxConcurrentKeys, int MaxConcurrentVoices);
internal sealed record Overlap(double Track1ActiveMs, double Track2ActiveMs, double OverlapMs,
    double RatioOfTrack2, double RatioOfTrack1, double Track2OnlyMs, int Track2Onsets,
    int Track2OnsetsDuringTrack1, double RatioTrack2OnsetsDuringTrack1);
internal sealed record PlanStats(int Output, double DurationMs, ConversionReport Report, GapStats Sound,
    OnsetStats Onsets, Density Density, Overlap AttributedTrackOverlap, int SustainShortened, List<string> Warnings);
internal sealed record PlanDelta(int AddedKeyOnsets, int RemovedKeyOnsets, int ChangedCommonKeyOnsets,
    int AddedDistinctTimes, int RemovedDistinctTimes, int AddedAttributedToTrack2, int AddedNativeChords,
    double OriginalKeyOnsetRetention, double Track2AddedDuringTrack1SoundRatio, int AddedTrack2NotesDuringTrack1Sound,
    double AddedTrack2ActiveMs, double AddedTrack2OverlapWithOriginalTrack1Ms, double AddedTrack2SoundOverlapRatio);
internal sealed record GapFill(double StartMs, double EndMs, double DurationMs, double RawTrack2CoverageMs,
    double CandidateSoundCoverageMs, double RemainingSilentMs);
internal sealed record MatrixRow(string Id, string Title, string Instrument, PlayOptions OriginalOptions,
    PlayOptions CandidateOptions, int RawTrack1Notes, int RawTrack2Notes, int RawExcludedNotes,
    GapStats RawTrack1Sound, GapStats RawTrack12Sound, OnsetStats RawTrack1Onsets, OnsetStats RawTrack12Onsets,
    Overlap RawTrackOverlap, PlanStats Original, PlanStats Candidate, PlanDelta Delta,
    List<GapFill> OriginalLongGapFill, bool Passed);

internal static class Metrics
{
    public const double Epsilon = .000001;
    public static bool Near(double a, double b) => Math.Abs(a - b) <= Epsilon;
    public static List<Span> Union(IEnumerable<Span> spans)
    {
        var result = new List<Span>();
        foreach (var span in spans.Where(s => s.EndMs > s.StartMs).OrderBy(s => s.StartMs).ThenBy(s => s.EndMs))
        {
            if (result.Count == 0 || span.StartMs > result[^1].EndMs + Epsilon) result.Add(span);
            else result[^1] = result[^1] with { EndMs = Math.Max(result[^1].EndMs, span.EndMs) };
        }
        return result;
    }
    public static double Intersect(IEnumerable<Span> left, IEnumerable<Span> right)
    {
        var a = Union(left); var b = Union(right); int i = 0, j = 0; double total = 0;
        while (i < a.Count && j < b.Count)
        {
            total += Math.Max(0, Math.Min(a[i].EndMs, b[j].EndMs) - Math.Max(a[i].StartMs, b[j].StartMs));
            if (a[i].EndMs < b[j].EndMs) i++; else j++;
        }
        return total;
    }
    public static GapStats Sound(IEnumerable<Span> spans, double duration)
    {
        var active = Union(spans); var gaps = active.Zip(active.Skip(1)).Select(p => new Span(p.First.EndMs, p.Second.StartMs)).ToList();
        var longGaps = gaps.Where(g => g.DurationMs >= 5000 - Epsilon).ToList();
        return new(longGaps.Count, longGaps.Sum(g => g.DurationMs), gaps.Select(g => g.DurationMs).DefaultIfEmpty(0).Max(),
            active.Count == 0 ? duration : active[0].StartMs, active.Count == 0 ? 0 : Math.Max(0, duration - active[^1].EndMs),
            active.Sum(s => s.DurationMs), longGaps);
    }
    public static OnsetStats Onsets(IEnumerable<double> starts)
    {
        var values = starts.Distinct().Order().ToArray();
        var gaps = values.Zip(values.Skip(1)).Select(p => new Span(p.First, p.Second)).ToList();
        var longs = gaps.Where(g => g.DurationMs >= 5000 - Epsilon).ToList();
        return new(values.Length, longs.Count, longs.Sum(g => g.DurationMs), gaps.Select(g => g.DurationMs).DefaultIfEmpty(0).Max(),
            values.FirstOrDefault(), values.LastOrDefault(), longs);
    }
    public static List<Span> Spans(IEnumerable<PlannedNote> notes) => notes.Select(n => new Span(n.StartMs, n.StartMs + n.SoundMs)).ToList();
    public static List<Span> Spans(IEnumerable<NoteEvent> notes, double speed) => notes.Select(n => new Span(n.StartMs / speed, (n.StartMs + n.DurationMs) / speed)).ToList();
    public static Overlap GetOverlap(List<Span> one, List<Span> two, IEnumerable<double> starts)
    {
        var u1 = Union(one); var u2 = Union(two); double a = u1.Sum(s => s.DurationMs), b = u2.Sum(s => s.DurationMs), o = Intersect(u1, u2);
        var onsets = starts.Distinct().ToList(); int during = onsets.Count(t => u1.Any(s => t >= s.StartMs && t < s.EndMs));
        return new(a, b, o, b == 0 ? 0 : o / b, a == 0 ? 0 : o / a, b - o, onsets.Count, during,
            onsets.Count == 0 ? 0 : (double)during / onsets.Count);
    }
    public static Density GetDensity(List<PlannedNote> notes)
    {
        int Voices(PlannedNote n) => n.ChordPitches?.Count ?? 1;
        int Sweep(bool voices)
        {
            // End events precede start events at equal times: intervals are [start,end).
            var events = notes.SelectMany(n => new[] { (Time: n.StartMs, Delta: voices ? Voices(n) : 1),
                (Time: n.StartMs + n.SoundMs, Delta: voices ? -Voices(n) : -1) }).OrderBy(e => e.Time).ThenBy(e => e.Delta);
            int current = 0, peak = 0; foreach (var e in events) { current += e.Delta; peak = Math.Max(peak, current); } return peak;
        }
        return new(notes.GroupBy(n => n.StartMs).Select(g => g.Count()).DefaultIfEmpty(0).Max(),
            notes.GroupBy(n => n.StartMs).Select(g => g.Sum(Voices)).DefaultIfEmpty(0).Max(), Sweep(false), Sweep(true));
    }
    public static PlanStats Plan(PlaybackPlan plan, int shortened) => new(plan.Notes.Count, plan.DurationMs, plan.Report,
        Sound(Spans(plan.Notes), plan.DurationMs), Onsets(plan.Notes.Select(n => n.StartMs)), GetDensity(plan.Notes),
        GetOverlap(Spans(plan.Notes.Where(n => n.Track == 1)), Spans(plan.Notes.Where(n => n.Track == 2)),
            plan.Notes.Where(n => n.Track == 2).Select(n => n.StartMs)), shortened, plan.Warnings);
    public static PlanDelta Delta(PlaybackPlan original, PlaybackPlan candidate)
    {
        var a = original.Notes.ToDictionary(n => (n.Key, n.StartMs)); var b = candidate.Notes.ToDictionary(n => (n.Key, n.StartMs));
        var added = b.Where(kv => !a.ContainsKey(kv.Key)).Select(kv => kv.Value).ToList();
        var timesA = a.Values.Select(n => n.StartMs).ToHashSet(); var timesB = b.Values.Select(n => n.StartMs).ToHashSet();
        var track2 = added.Where(n => n.Track == 2).ToList(); var u1 = Union(Spans(original.Notes));
        int during = track2.Count(n => u1.Any(s => n.StartMs >= s.StartMs && n.StartMs < s.EndMs));
        double addedActive = Union(Spans(track2)).Sum(s => s.DurationMs), addedOverlap = Intersect(u1, Spans(track2));
        bool Equal(PlannedNote x, PlannedNote y) => x.Pitch == y.Pitch && x.Key == y.Key && x.StartMs == y.StartMs && x.HoldMs == y.HoldMs
            && x.SoundMs == y.SoundMs && x.Velocity == y.Velocity && x.Track == y.Track && x.Sustain == y.Sustain
            && (x.ChordPitches ?? []).SequenceEqual(y.ChordPitches ?? []);
        return new(added.Count, a.Keys.Count(k => !b.ContainsKey(k)), a.Keys.Count(k => b.TryGetValue(k, out var n) && !Equal(a[k], n)),
            timesB.Except(timesA).Count(), timesA.Except(timesB).Count(), track2.Count, added.Count(n => n.ChordPitches != null),
            (double)a.Keys.Count(b.ContainsKey) / a.Count, track2.Count == 0 ? 0 : (double)during / track2.Count, during,
            addedActive, addedOverlap, addedActive == 0 ? 0 : addedOverlap / addedActive);
    }
}

