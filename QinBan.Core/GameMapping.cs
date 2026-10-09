// Derived from AutoMidiPlayer.WPF/Core/KeyboardPlayer.cs (TransposeNote/folding)
// and Core/Games/Genshin/Instruments/WindsongLyre.cs, upstream commit
// d479e6ee89e520daaf34dbda6ff004a2ef3f0ef3. Original copyright Jed556 / sabihoshi.
// QinBan adaptation: deterministic reporting, safe ranges, chord modes and no native input here.
// GPL-3.0; see ../LICENSE and ../QINBAN-NOTICES.md.
namespace QinBan.Core;

public static class GameMapping
{
    public const string Keys = "QWERTYUASDFGHJZXCVBNM";
    public static readonly int[] Pitches = [72, 74, 76, 77, 79, 81, 83, 60, 62, 64, 65, 67, 69, 71, 48, 50, 52, 53, 55, 57, 59];
    public static readonly int[] SortedPitches = Pitches.Order().ToArray();
    public static int PitchForKey(char key)
    {
        int index = Keys.IndexOf(char.ToUpperInvariant(key));
        if (index < 0) throw new FormatException($"不是原神 21 键中的按键：{key}");
        return Pitches[index];
    }
    public static char KeyForPitch(int pitch) => Keys[Array.IndexOf(Pitches, pitch)];
    public static string NoteName(int pitch) => new[] { "C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B" }[pitch % 12] + (pitch / 12 - 1);

    public static PlaybackPlan Build(SongDocument song, PlayOptions options, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested(); SongParser.Validate(song); options.Validate();
        var instrument = InstrumentCatalog.Get(options.InstrumentId);
        var warnings = new List<string>(song.Warnings);
        warnings.Add(instrument.Name + "：" + instrument.Note);
        if (!instrument.CanAutoPlay)
            return new([], 0, new(song.Notes.Count, 0, 0, 0, song.Notes.Count, 0, 0), warnings);
        var melody = instrument.MelodyKeys;
        var supported = melody.Select(k => k.Pitches[0]).Order().ToArray();
        int minimum = supported[0], maximumPitch = supported[^1];
        int folded = 0, accidental = 0, skipped = 0, simplified = 0, duplicate = 0, nativeChords = 0;
        var result = new List<PlannedNote>();
        var arrangement = SmartInterludeArranger.Arrange(song, options, cancellationToken);
        var source = arrangement.Notes.OrderBy(n => n.StartMs).ToList();
        if (arrangement.Enabled) warnings.Add(arrangement.AddedNotes > 0
            ? $"智能衔接：从未选声部接续 {arrangement.AddedNotes} 个原谱音符 / {arrangement.Segments} 段长休止；保留原起音和时值，不压缩时间。"
            : "智能衔接：没有需要且可以安全接续的长休止；保留手动选轨与原谱休止。 ");
        skipped = song.Notes.Count - source.Count;
        if (source.Any(n => n.Percussion)) warnings.Add("选中的打击乐轨被作为旋律音高适配，不会还原原始鼓声；建议排除打击乐。");
        PlannedNote Plan(NoteEvent n, InstrumentKey key, double shift = 0)
        {
            double sound = n.DurationMs / options.Speed;
            double hold = options.HoldByScore && instrument.SupportsSustain ? sound : options.HoldMs;
            return new(key.Pitches[0], key.Key, n.StartMs / options.Speed + shift, hold, sound,
                n.Velocity, n.Track, key.IsChord ? key.Pitches : null, instrument.SupportsSustain);
        }
        // Native guitar chords are recognized from the existing EXACT equal-time pitch classes,
        // before folding/accidental replacement. No accompaniment is invented from a melody.
        foreach (var group in source.GroupBy(n => n.StartMs))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var groupNotes = group.ToList();
            var classes = groupNotes.Select(n => ((n.Pitch + options.Transpose + options.Octave * 12) % 12 + 12) % 12).Distinct().Order().ToArray();
            var chord = options.NativeGuitarChords && options.Chords == ChordMode.Simultaneous && !groupNotes.Any(n => n.Percussion)
                ? instrument.Keys.FirstOrDefault(k => k.IsChord && k.Pitches.Count <= options.MaxChordNotes && k.Pitches.Select(p => p % 12).Distinct().Order().SequenceEqual(classes)) : null;
            if (chord != null)
            {
                var basis = groupNotes.OrderByDescending(n => n.Velocity).First() with { DurationMs = groupNotes.Min(n => n.DurationMs) };
                result.Add(Plan(basis, chord)); nativeChords++; continue;
            }
            var mapped = new List<(NoteEvent Note, InstrumentKey Key)>();
            foreach (var note in groupNotes)
            {
                cancellationToken.ThrowIfCancellationRequested();
                int pitch = note.Pitch + options.Transpose + options.Octave * 12;
                if (pitch < minimum || pitch > maximumPitch)
                {
                    if (options.Range == RangeMode.Skip) { skipped++; continue; }
                    while (pitch < minimum) pitch += 12;
                    while (pitch > maximumPitch) pitch -= 12;
                    folded++;
                }
                if (!supported.Contains(pitch))
                {
                    if (options.Accidentals == AccidentalMode.Skip) { skipped++; continue; }
                    var candidates = options.Accidentals switch
                    {
                        AccidentalMode.Lower => supported.Where(p => p <= pitch),
                        AccidentalMode.Upper => supported.Where(p => p >= pitch),
                        _ => supported.AsEnumerable()
                    };
                    pitch = candidates.OrderBy(p => Math.Abs(p - pitch)).ThenBy(p => p).First(); accidental++;
                }
                mapped.Add((note, melody.First(k => k.Pitches[0] == pitch)));
            }
            var unique = mapped.GroupBy(n => n.Key.Key).Select(g => g.OrderByDescending(n => n.Note.Velocity).First()).ToList();
            duplicate += mapped.Count - unique.Count;
            int maximum = options.Chords == ChordMode.MelodyOnly ? 1 : options.MaxChordNotes;
            var chosen = unique.OrderByDescending(n => n.Key.Pitches[0]).Take(maximum).ToList();
            simplified += unique.Count - chosen.Count;
            chosen = options.Chords == ChordMode.Descending ? chosen.OrderByDescending(n => n.Key.Pitches[0]).ToList() : chosen.OrderBy(n => n.Key.Pitches[0]).ToList();
            for (int i = 0; i < chosen.Count; i++)
            {
                var (note, key) = chosen[i];
                double shift = options.Chords is ChordMode.Ascending or ChordMode.Descending ? i * options.StrumMs : 0;
                result.Add(Plan(note, key, shift));
            }
        }
        cancellationToken.ThrowIfCancellationRequested();
        int beforeShiftMerge = result.Count;
        result = result.GroupBy(n => (n.Key, n.StartMs)).Select(g => g.OrderByDescending(n => n.Velocity).First()).ToList();
        duplicate += beforeShiftMerge - result.Count;
        result = result.OrderBy(n => n.StartMs).ThenBy(n => n.Pitch).ToList();
        // Release before another attack on the same key; never flatten onset timing or rests.
        foreach (var indices in result.Select((n, i) => (n, i)).GroupBy(x => x.n.Key))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var list = indices.OrderBy(x => x.n.StartMs).ToList();
            for (int i = 0; i < list.Count - 1; i++)
            {
                var current = result[list[i].i];
                double gap = list[i + 1].n.StartMs - current.StartMs;
                double end = Math.Max(.1, gap - Math.Min(8, gap / 4));
                result[list[i].i] = current with { HoldMs = Math.Min(current.HoldMs, end), SoundMs = current.Sustain ? Math.Min(current.SoundMs, end) : current.SoundMs };
            }
        }
        double duration = result.Count == 0 ? 0 : Math.Max(song.DurationMs / options.Speed, result.Max(n => n.StartMs + n.HoldMs));
        if (result.Count == 0) warnings.Add("当前轨道和适配设置下没有可演奏音符。");
        if (result.GroupBy(n => n.Key).Any(g => g.Zip(g.Skip(1)).Any(pair => pair.Second.StartMs - pair.First.StartMs < 45)))
            warnings.Add("存在同键间隔小于 45ms 的快速段；游戏可能漏音，建议降低速度。");
        cancellationToken.ThrowIfCancellationRequested();
        return new(result, duration, new(song.Notes.Count, result.Count, folded, accidental, skipped, simplified, duplicate, nativeChords, arrangement.AddedNotes, arrangement.Segments), warnings);
    }
}
