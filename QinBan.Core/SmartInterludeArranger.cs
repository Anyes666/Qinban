namespace QinBan.Core;

/// <summary>
/// Source-only voice handoff. Selected tracks remain the foundation. Never quantizes,
/// shifts, clips, re-attacks or invents notes; candidates must fit entirely in a rest.
/// All thresholds use the original score clock, independent of playback speed.
/// </summary>
public static class SmartInterludeArranger
{
    public const double MinimumGapMs = 3000;
    private const double FallbackGapMs = 1500;
    private const double Epsilon = .000001;
    private readonly record struct Span(double Start, double End);
    internal sealed record Selection(List<NoteEvent> Notes, bool Enabled, int AddedNotes, int Segments);

    public static bool IsEnabled(SongDocument song, PlayOptions options) => options.SmartInterludes
        ?? string.Equals(song.Provenance.Provider, "POP909", StringComparison.OrdinalIgnoreCase);

    internal static Selection Arrange(SongDocument song, PlayOptions options, CancellationToken cancel)
    {
        cancel.ThrowIfCancellationRequested();
        bool enabled = IsEnabled(song, options);
        var selected = options.Tracks?.ToHashSet();
        var basis = song.Notes.Where(n => (selected == null || selected.Contains(n.Track))
            && (!options.ExcludePercussion || !n.Percussion)).ToList();
        if (!enabled || selected == null || basis.Count == 0) return new(basis, enabled, 0, 0);
        var candidates = song.Notes.Where(n => !selected.Contains(n.Track) && !n.Percussion).ToList();
        if (candidates.Count == 0) return new(basis, true, 0, 0);

        var instrument = InstrumentCatalog.Get(options.InstrumentId);
        var occupied = new List<Span>();
        foreach (var group in basis.GroupBy(n => n.StartMs))
        {
            // Leave room for existing arpeggiation and physical key holds as well as
            // source note tails. A handoff must not steal a delayed primary attack.
            double spread = options.Chords is ChordMode.Ascending or ChordMode.Descending
                ? (Math.Min(group.Count(), options.MaxChordNotes) - 1) * options.StrumMs * options.Speed : 0;
            foreach (var n in group)
            {
                double held = options.HoldByScore && instrument.SupportsSustain ? n.DurationMs : options.HoldMs * options.Speed;
                occupied.Add(new(n.StartMs, Math.Min(song.DurationMs, n.StartMs + Math.Max(n.DurationMs, held) + spread + 8 * options.Speed)));
            }
        }
        // Classify musical rests on source note-offs first. Keyboard-release padding
        // narrows usable edges, but must not turn an exact 3-second rest into a short one.
        var musicalRests = Gaps(Union(basis.Select(n => new Span(n.StartMs, n.StartMs + n.DurationMs))),
            new Span(0, song.DurationMs)).Where(s => s.End - s.Start + Epsilon >= MinimumGapMs).ToList();
        var free = Gaps(Union(occupied), new Span(0, song.DurationMs));
        var rests = Intersect(musicalRests, free);
        if (rests.Count == 0) return new(basis, true, 0, 0);
        bool pop = string.Equals(song.Provenance.Provider, "POP909", StringComparison.OrdinalIgnoreCase);
        // POP909 documents tracks 1=MELODY, 2=BRIDGE, 3=PIANO. Other scores have
        // no reliable role metadata in native JSON: prefer sparser tracks at equal onsets.
        var ranks = candidates.GroupBy(n => n.Track).OrderBy(g => pop ? g.Key : g.Count())
            .ThenBy(g => g.Key).Select((g, i) => (g.Key, Rank: i)).ToDictionary(x => x.Key, x => x.Rank);
        var primary = Groups(candidates.Where(n => !pop || n.Track != 3), ranks);
        var piano = Groups(candidates.Where(n => pop && n.Track == 3), ranks);
        var additions = new List<NoteEvent>(); int segments = 0;
        foreach (var rest in rests)
        {
            cancel.ThrowIfCancellationRequested();
            var line = new List<NoteEvent>();
            AddLine(primary, rest, line, cancel);
            if (piano.Count > 0)
            {
                var remaining = Gaps(Union(line.Select(n => new Span(n.StartMs, n.StartMs + n.DurationMs))), rest);
                foreach (var space in remaining.Where(s => s.End - s.Start + Epsilon >= FallbackGapMs))
                    AddLine(piano, space, line, cancel);
            }
            if (line.Count > 0) { additions.AddRange(line); segments++; }
        }
        cancel.ThrowIfCancellationRequested();
        basis.AddRange(additions);
        return new(basis, true, additions.Count, segments);
    }

    private sealed record Onset(double Start, List<NoteEvent> Notes);
    private static List<Onset> Groups(IEnumerable<NoteEvent> notes, Dictionary<int, int> ranks) => notes
        .GroupBy(n => n.StartMs).OrderBy(g => g.Key)
        .Select(g => new Onset(g.Key, g.OrderBy(n => ranks[n.Track]).ThenByDescending(n => n.Pitch)
            .ThenByDescending(n => n.Velocity).ThenBy(n => n.DurationMs).ToList())).ToList();

    private static void AddLine(List<Onset> groups, Span window, List<NoteEvent> output, CancellationToken cancel)
    {
        // Binary search avoids rescanning a whole track for every gap in a long MIDI.
        int lo = 0, hi = groups.Count;
        while (lo < hi) { int mid = lo + (hi - lo) / 2; if (groups[mid].Start < window.Start) lo = mid + 1; else hi = mid; }
        double available = window.Start;
        for (int i = lo; i < groups.Count && groups[i].Start < window.End; i++)
        {
            cancel.ThrowIfCancellationRequested(); var group = groups[i];
            if (group.Start < available) continue;
            var note = group.Notes.FirstOrDefault(n => n.StartMs + n.DurationMs <= window.End);
            if (note == null) continue;
            output.Add(note); available = note.StartMs + note.DurationMs;
        }
    }

    private static List<Span> Intersect(List<Span> musical, List<Span> safe)
    {
        var result = new List<Span>(); int at = 0;
        foreach (var rest in musical)
        {
            while (at < safe.Count && safe[at].End <= rest.Start) at++;
            for (int i = at; i < safe.Count && safe[i].Start < rest.End; i++)
            {
                double start = Math.Max(rest.Start, safe[i].Start), end = Math.Min(rest.End, safe[i].End);
                if (end > start) result.Add(new(start, end));
            }
        }
        return result;
    }

    private static List<Span> Union(IEnumerable<Span> values)
    {
        var result = new List<Span>();
        foreach (var s in values.OrderBy(s => s.Start).ThenBy(s => s.End))
        {
            if (result.Count > 0 && s.Start <= result[^1].End)
                result[^1] = result[^1] with { End = Math.Max(result[^1].End, s.End) };
            else result.Add(s);
        }
        return result;
    }
    private static List<Span> Gaps(List<Span> active, Span window)
    {
        var gaps = new List<Span>(); double at = window.Start;
        foreach (var span in active)
        {
            if (span.Start > at) gaps.Add(new(at, Math.Min(span.Start, window.End)));
            at = Math.Max(at, span.End);
        }
        if (at < window.End) gaps.Add(new(at, window.End));
        return gaps;
    }
}