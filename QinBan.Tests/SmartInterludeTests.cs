using System.Text;
using System.Text.Json;
using QinBan.Core;

static class SmartInterludeTests
{
    public static void Run(string fixtures, Action<string, Action> sync, Action<bool, string> check)
    {
        string Json<T>(T value) => JsonSerializer.Serialize(value, JsonDefaults.Options);
        string Signature(PlannedNote note) => Json(note);
        PlaybackPlan Disabled(SongDocument song, PlayOptions options)
        {
            var disabled = options.Copy(); disabled.SmartInterludes = false;
            return GameMapping.Build(song, disabled);
        }
        void SamePlan(PlaybackPlan actual, PlaybackPlan expected, string why)
        {
            check(actual.Notes.Select(Signature).SequenceEqual(expected.Notes.Select(Signature)), why + ": notes changed");
            check(actual.DurationMs == expected.DurationMs, why + ": duration changed");
            check(actual.Report.Output == actual.Notes.Count, why + ": output report disagrees with plan");
        }
        List<(double Start, double End)> OriginalRests(SongDocument song, PlayOptions options)
        {
            var selected = options.Tracks?.ToHashSet();
            var main = song.Notes.Where(n => (selected == null || selected.Contains(n.Track))
                && (!options.ExcludePercussion || !n.Percussion)).OrderBy(n => n.StartMs).ToList();
            var rests = new List<(double Start, double End)>();
            if (main.Count == 0) return rests;
            // Eligibility is musical: use original note-offs and the source clock. Do not
            // reimplement the arranger's physical-hold/strum/release-safe window selection.
            double end = 0;
            foreach (var note in main)
            {
                if (note.StartMs - end >= 3000) rests.Add((end, note.StartMs));
                end = Math.Max(end, note.StartMs + note.DurationMs);
            }
            if (song.DurationMs - end >= 3000) rests.Add((end, song.DurationMs));
            return rests;
        }
        List<PlannedNote> Added(SongDocument song, PlayOptions options, PlaybackPlan actual, bool preserveAllMainFields = true)
        {
            var baseline = Disabled(song, options);
            var actualNotes = actual.Notes.Select(Signature).ToHashSet(StringComparer.Ordinal);
            var actualAttacks = actual.Notes.Select(n => (n.Key, n.StartMs)).ToHashSet();
            var mainNotes = baseline.Notes.Select(Signature).ToHashSet(StringComparer.Ordinal);
            foreach (var note in baseline.Notes)
                check(preserveAllMainFields ? actualNotes.Contains(Signature(note)) : actualAttacks.Contains((note.Key, note.StartMs)),
                    "interlude removed/retimed/changed a selected main note or chord");
            var added = actual.Notes.Where(n => !mainNotes.Contains(Signature(n))).OrderBy(n => n.StartMs).ToList();
            if (!preserveAllMainFields) added = added.Where(n => options.Tracks == null || !options.Tracks.Contains(n.Track)).ToList();
            check(added.Count > 0, "eligible unselected source voice did not supplement the long gap");
            check(actual.Report.Output == actual.Notes.Count, "output report disagrees with supplemented plan");

            // Directly playable pitches let the complete mapped tuple prove that EACH addition comes
            // from ONE intact NoteEvent, not onset/duration/pitch/velocity combined from several events.
            // Lookups and gap search are bounded, not a full source scan for every output note.
            var selected = options.Tracks?.ToHashSet();
            var instrument = InstrumentCatalog.Get(options.InstrumentId);
            var candidates = new Dictionary<string, NoteEvent>(StringComparer.Ordinal);
            foreach (var note in song.Notes.Where(n => selected != null && !selected.Contains(n.Track) && !n.Percussion))
            {
                int pitch = note.Pitch + options.Transpose + options.Octave * 12;
                var key = instrument.MelodyKeys.FirstOrDefault(k => k.Pitches[0] == pitch);
                if (key == null) continue;
                double sound = note.DurationMs / options.Speed;
                double hold = options.HoldByScore && instrument.SupportsSustain ? sound : options.HoldMs;
                var expected = new PlannedNote(pitch, key.Key, note.StartMs / options.Speed, hold, sound,
                    note.Velocity, note.Track, null, instrument.SupportsSustain);
                candidates.TryAdd(Signature(expected), note);
            }
            var gaps = OriginalRests(song, options);
            foreach (var note in added)
            {
                if (!candidates.TryGetValue(Signature(note), out var source))
                {
                    check(false, "addition is not one exact non-percussion, unselected source event after mapping");
                    continue;
                }
                // Every complete source event must stay in an eligible original rest; edge safety is tested via baseline preservation.
                int low = 0, high = gaps.Count;
                while (low < high)
                {
                    int middle = (low + high) / 2;
                    if (gaps[middle].Start <= source.StartMs) low = middle + 1; else high = middle;
                }
                int index = low - 1;
                check(index >= 0 && source.StartMs >= gaps[index].Start
                    && source.StartMs + source.DurationMs <= gaps[index].End,
                    "addition crosses original selected activity or a <3s source rest");
                check(note.ChordPitches == null || note.ChordPitches.Count <= 1, "supplement invented a chord from separate source voices");
            }
            for (int i = 1; i < added.Count; i++)
                check(added[i - 1].StartMs + added[i - 1].SoundMs <= added[i].StartMs,
                    "supplement is polyphonic/overlapping or shortened a source event to fit another attack");
            return added;
        }

        sync("Smart interlude null inherits enabled only from POP909 provenance", () =>
        {
            var song = BridgeSong(); var options = Options();
            check(options.SmartInterludes == null, "new options did not retain nullable inheritance");
            var added = Added(song, options, GameMapping.Build(song, options));
            check(added.Any(n => n.Track == 2), "POP909 secondary melody was not used");
            check(options.SmartInterludes == null, "inheritance was written back as an explicit choice");
        });
        sync("Smart interlude other providers and a POP909 source label remain disabled by default", () =>
        {
            foreach (string provider in new[] { "local", "midi", "teaching", "POP909-copy" })
            {
                var song = BridgeSong(); song.Provenance.Provider = provider; song.Source = "POP909";
                var options = Options(); SamePlan(GameMapping.Build(song, options), Disabled(song, options), provider);
                check(GameMapping.Build(song, options).Notes.Count == 2, "source text enabled a non-POP909 score");
            }
        });
        sync("Smart interlude explicit true overrides a non-POP909 provider", () =>
        {
            var song = BridgeSong(); song.Provenance.Provider = "local"; var options = Options(true);
            Added(song, options, GameMapping.Build(song, options));
        });
        sync("Smart interlude explicit false restores the legacy selected-track plan", () =>
        {
            var song = BridgeSong(); var options = Options(false);
            var legacySong = song.Copy(); legacySong.Provenance.Provider = "local";
            var legacyOptions = options.Copy(); legacyOptions.SmartInterludes = null;
            var actual = GameMapping.Build(song, options);
            SamePlan(actual, GameMapping.Build(legacySong, legacyOptions), "explicit off did not restore old plan");
            check(actual.Notes.Count == 2 && actual.Notes.All(n => n.Track == 1), "off retained bridge events");
        });
        sync("Smart interlude nullable choice survives copy, JSON and legacy missing-field options", () =>
        {
            var legacy = JsonSerializer.Deserialize<PlayOptions>("{\"tracks\":[1],\"speed\":1}", JsonDefaults.Options)!;
            check(legacy.SmartInterludes == null, "legacy options no longer inherit by provider");
            var song = BridgeSong(); Added(song, legacy, GameMapping.Build(song, legacy));
            foreach (bool? choice in new bool?[] { null, true, false })
            {
                var original = Options(choice);
                foreach (var copy in new[] { original.Copy(), JsonSerializer.Deserialize<PlayOptions>(Json(original), JsonDefaults.Options)! })
                {
                    check(copy.SmartInterludes == choice && copy.Tracks!.SequenceEqual(new[] { 1 }), "choice lost on option round-trip");
                    check(!ReferenceEquals(copy.Tracks, original.Tracks), "copied selection aliases caller options");
                    copy.Tracks!.Add(9); check(original.Tracks!.SequenceEqual(new[] { 1 }), "copy mutated original selection");
                }
            }
        });
        sync("Smart interlude isolated LibraryStore reload remembers explicit off without changing source", () =>
        {
            string root = Path.Combine(fixtures, "smart-interlude-state-" + Guid.NewGuid().ToString("N"));
            string songs = Path.Combine(root, "catalog-resources"); Directory.CreateDirectory(songs);
            string source = Path.Combine(songs, "fixture.json");
            File.WriteAllText(source, SongParser.ToJson(BridgeSong()), new UTF8Encoding(false));
            string sourceHash = LibraryCatalog.HashFile(source);
            var entry = LibraryStore.Create(BridgeSong(), "fixture.json", sourceHash, true);
            entry.Id = entry.CatalogId = "smart:fixture";
            string catalog = Path.Combine(songs, LibraryCatalog.FileName); LibraryCatalog.Build(catalog, [entry], songs);
            string catalogHash = LibraryCatalog.HashFile(catalog), data = Path.Combine(root, "isolated-state");
            var store = new LibraryStore(data, songs); var saved = store.Find(entry.Id)!;
            saved.Options = Options(false).Copy(); store.Save(saved);
            var reopened = new LibraryStore(data, songs); var restored = reopened.Find(entry.Id)!;
            check(restored.Options.SmartInterludes == false && restored.Options.Tracks!.SequenceEqual(new[] { 1 }), "store lost explicit off");
            var song = reopened.LoadSong(restored);
            SamePlan(GameMapping.Build(song, restored.Options), Disabled(song, restored.Options), "reload ignored remembered off");
            check(GameMapping.Build(song, restored.Options).Notes.Count == 2, "reload used provider default instead of remembered off");
            restored.Options.SmartInterludes = null; reopened.Save(restored);
            var third = new LibraryStore(data, songs); var inherited = third.Find(entry.Id)!;
            check(inherited.Options.SmartInterludes == null, "store collapsed inherited choice to false");
            var inheritedSong = third.LoadSong(inherited);
            Added(inheritedSong, inherited.Options, GameMapping.Build(inheritedSong, inherited.Options));
            check(sourceHash == LibraryCatalog.HashFile(source) && catalogHash == LibraryCatalog.HashFile(catalog), "saving choice changed source/catalogue");
        });
        sync("Smart interlude null selection and explicit allTracks never supplement the full source", () =>
        {
            var song = BridgeSong();
            foreach (var tracks in new List<int>?[] { null, song.Tracks.Select(t => t.Id).ToList() })
            {
                var options = Options(true); options.Tracks = tracks;
                SamePlan(GameMapping.Build(song, options), Disabled(song, options), "all-source selection changed");
            }
        });
        sync("Smart interlude empty Tracks is an intentional silent selection", () =>
        {
            var song = BridgeSong(); var options = Options(true); options.Tracks = [];
            var plan = GameMapping.Build(song, options);
            check(plan.Notes.Count == 0 && plan.DurationMs == 0, "empty selection was repopulated");
            SamePlan(plan, Disabled(song, options), "empty selection");
        });
        sync("Smart interlude absent selected melody does not turn unselected voices into a full song", () =>
        {
            var song = Song(10000, new(72, 1000, 500, 2), new(67, 5000, 500, 3));
            var options = Options(true); var plan = GameMapping.Build(song, options);
            check(plan.Notes.Count == 0, "missing selected track invented a main melody");
            SamePlan(plan, Disabled(song, options), "missing selected melody");
        });
        sync("Smart interlude never borrows drums even when global percussion exclusion is off", () =>
        {
            var song = Song(6500, new(60, 0, 500, 1), new(62, 6000, 500, 1),
                new(76, 2000, 500, 9, 120, true));
            var options = Options(true); options.ExcludePercussion = false;
            SamePlan(GameMapping.Build(song, options), Disabled(song, options), "percussion was treated as bridge melody");
        });
        sync("Smart interlude held main notes are activity, not inter-onset gaps", () =>
        {
            var song = Song(9000, new(60, 0, 8000, 1), new(62, 8500, 500, 1),
                new(72, 2000, 500, 2), new(67, 5000, 500, 3));
            var options = Options(true);
            SamePlan(GameMapping.Build(song, options), Disabled(song, options), "long sounding main note was filled over");
        });
        sync("Smart interlude overlapping main activity uses the latest note-off, not the last onset", () =>
        {
            var song = Song(10500, new(60, 0, 9000, 1), new(64, 2000, 250, 1), new(62, 10000, 500, 1),
                new(72, 4000, 500, 2), new(67, 7000, 500, 3));
            var options = Options(true);
            SamePlan(GameMapping.Build(song, options), Disabled(song, options), "nested short note falsely ended main activity");
        });
        sync("Smart interlude mapping-skipped main pitches still block their original sounding interval", () =>
        {
            var song = Song(7000, new(100, 0, 6000, 1), new(60, 6500, 500, 1), new(72, 1500, 500, 2));
            var options = Options(true); options.Range = RangeMode.Skip;
            SamePlan(GameMapping.Build(song, options), Disabled(song, options), "post-mapping omission created an artificial gap");
        });
        sync("Smart interlude a real all-track rest and silent tail never synthesize notes", () =>
        {
            var song = Song(15000, new(60, 0, 500, 1), new(62, 10000, 500, 1),
                new(72, 50, 200, 2), new(67, 10100, 200, 3));
            var options = Options(true);
            SamePlan(GameMapping.Build(song, options), Disabled(song, options), "global rest was fabricated into accompaniment");
        });
        sync("Smart interlude three-second threshold is inclusive and measured before speed scaling", () =>
        {
            foreach (double gap in new[] { 2999.999, 3000, 3000.25 })
            foreach (double speed in new[] { .5, 1, 2, 3 })
            {
                var song = Song(1000 + gap, new(60, 0, 500, 1), new(62, 500 + gap, 500, 1),
                    new(72, 1000.125, 333.5, 2));
                var options = Options(true); options.Speed = speed; var plan = GameMapping.Build(song, options);
                if (gap < 3000) SamePlan(plan, Disabled(song, options), "sub-threshold gap at speed " + speed);
                else Added(song, options, plan);
            }
        });
        sync("Smart interlude long leading and trailing activity blanks both accept source notes", () =>
        {
            var song = Song(14000, new(60, 6000, 500, 1), new(72, 0, 600, 2),
                new(74, 3000, 500, 2), new(76, 7500, 500, 2), new(79, 13000, 1000, 2), new(67, 10500, 500, 3));
            var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
            check(added.Any(n => n.StartMs < 6000) && added.Any(n => n.StartMs >= 6500), "head or tail gap was ignored");
        });
        sync("Smart interlude safe-window boundary note-on and note-off fit without moving or trimming", () =>
        {
            foreach (double speed in new[] { .5, 1, 2, 3 })
            {
                double safeStart = 1500 + 8 * speed;
                foreach (var candidate in new NoteEvent[] { new(72, safeStart, 5500 - safeStart, 2),
                    new(72, safeStart, 500, 2), new(72, 5000, 500, 2) })
                {
                    var song = Song(6500, new(60, 1000, 500, 1), new(62, 5500, 1000, 1), candidate);
                    var options = Options(true); options.Speed = speed;
                    // Still require a real addition, matching the intact source event at either
                    // safe edge (or spanning the whole safe window), not a clipped replacement.
                    Added(song, options, GameMapping.Build(song, options));
                }
            }
        });
        sync("Smart interlude partial overlap at either boundary and a spanning note are rejected whole", () =>
        {
            var song = Song(6500, new(60, 0, 500, 1), new(62, 6000, 500, 1),
                new(72, 499.75, 1000, 2), new(74, 5900, 100.25, 2), new(76, 250, 6500, 2), new(67, 2000, 600, 3));
            var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
            check(added.All(n => n.Track == 3), "overlapping secondary notes were clipped/moved rather than rejected");
        });
        sync("Smart interlude POP909 track two beats louder or higher piano and chooses its high voice", () =>
        {
            var song = Song(8500, new(60, 0, 500, 1), new(62, 8000, 500, 1),
                new(60, 1500, 600, 2, 125), new(72, 1500, 600, 2, 40), new(74, 3500, 500, 2), new(79, 1500, 700, 3, 127));
            var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
            check(added.Any(n => n.StartMs == 1500 && n.Track == 2 && n.Pitch == 72 && n.Velocity == 40), "voice priority/high pitch replaced by velocity or piano pitch");
            check(!added.Any(n => n.Track == 3 && n.StartMs == 1500), "piano displaced/overlapped the secondary voice");
        });
        sync("Smart interlude same-beat high voice and overlapping later attacks stay source-exact and monophonic", () =>
        {
            var song = Song(8000, new(60, 0, 500, 1), new(62, 7500, 500, 1),
                new(64, 1000, 1300, 2, 120), new(72, 1000, 1600, 2, 100), new(76, 1000, 1000, 2, 42),
                new(74, 1100, 250, 2), new(79, 2500, 600, 2), new(67, 1100, 500, 3));
            var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
            check(added.Any(n => n.StartMs == 1000 && n.Pitch == 76 && n.Velocity == 42), "same-beat highest source voice was lost");
        });
        sync("Smart interlude missing secondary melody falls back to high single piano voices", () =>
        {
            var song = Song(8500, new(60, 0, 500, 1), new(62, 8000, 500, 1),
                new(60, 2000, 400, 3), new(64, 2000, 400, 3), new(67, 2000, 400, 3),
                new(62, 4500, 400, 3), new(65, 4500, 400, 3), new(69, 4500, 400, 3));
            var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
            check(added.All(n => n.Track == 3) && added.Any(n => n.StartMs == 2000 && n.Pitch == 67), "piano fallback missing or retained dense lower voices");
        });
        sync("Smart interlude piano continuation uses residual blanks only at or above one-and-a-half seconds", () =>
        {
            // Start the bridge safely inside the window; its unchanged end still leaves
            // exactly the tested residual before the next main onset at 3500ms.
            foreach (double residual in new[] { 1499.75, 1500, 1500.25 })
            {
                var song = Song(4000, new(60, 0, 500, 1), new(62, 3500, 500, 1),
                    new(72, 600, 2900 - residual, 2), new(67, 2250, 500, 3));
                var options = Options(true); var added = Added(song, options, GameMapping.Build(song, options));
                check(added.Any(n => n.Track == 2), "piano continuation replaced its primary secondary voice");
                check(added.Any(n => n.Track == 3) == (residual >= 1500), "piano residual threshold is wrong: " + residual);
            }
        });
        sync("Smart interlude a selected non-melody track remains the base when POP909 melody track is absent", () =>
        {
            var song = Song(6500, new(60, 0, 500, 2), new(62, 6000, 500, 2),
                new(67, 2000, 500, 3), new(69, 3500, 500, 3));
            var options = Options(); options.Tracks = [2];
            var added = Added(song, options, GameMapping.Build(song, options));
            check(added.All(n => n.Track == 3), "arranger hardcoded missing track one instead of caller selection");
        });
        sync("Smart interlude multiple selected tracks and same-beat main chords survive every chord mode", () =>
        {
            var song = Song(8500, new(60, 0, 500, 1), new(64, 0, 500, 1), new(67, 0, 500, 1), new(72, 0, 300, 4),
                new(62, 8000, 500, 1), new(65, 8000, 500, 1), new(69, 8000, 500, 1), new(74, 8000, 500, 4), new(76, 1500, 500, 2));
            foreach (ChordMode mode in Enum.GetValues<ChordMode>())
            {
                var options = Options(true); options.Tracks = [1, 4]; options.Chords = mode;
                options.StrumMs = 37; options.InstrumentId = "piano";
                Added(song, options, GameMapping.Build(song, options));
            }
        });
        sync("Smart interlude native guitar chords cannot mix with bridge voices or dense piano chords", () =>
        {
            var song = Song(8500, new(60, 0, 500, 1), new(64, 0, 500, 1), new(67, 0, 500, 1),
                new(62, 8000, 500, 1), new(65, 8000, 500, 1), new(69, 8000, 500, 1),
                new(69, 0, 250, 2), new(72, 8000, 250, 2), new(60, 2000, 500, 3), new(64, 2000, 500, 3), new(67, 2000, 500, 3));
            var options = Options(true); options.InstrumentId = "ukulele";
            var baseline = Disabled(song, options); check(baseline.Report.NativeChords == 2, "fixture does not exercise existing guitar chords");
            var plan = GameMapping.Build(song, options); var added = Added(song, options, plan);
            check(plan.Report.NativeChords == baseline.Report.NativeChords && added.All(n => n.ChordPitches == null), "bridge changed/invented native guitar chord groups");
        });
        sync("Smart interlude speed, transpose, octave, instrument and score/fixed hold apply exactly once", () =>
        {
            var song = Song(7500, new(60, 0, 500, 1), new(62, 7000, 500, 1),
                new(65, 1600.25, 400.5, 2, 47), new(67, 3500, 600, 2, 111));
            foreach (string instrument in new[] { "windsong", "piano", "voice", "horn" })
            foreach (bool byScore in new[] { true, false })
            {
                var options = Options(true); options.InstrumentId = instrument; options.Speed = 2;
                options.Transpose = 2; options.Octave = instrument == "horn" ? 0 : 1;
                options.HoldByScore = byScore; options.HoldMs = 91;
                Added(song, options, GameMapping.Build(song, options));
            }
        });
        sync("Smart interlude original chord delayed attacks and strum tails stay protected", () =>
        {
            foreach (ChordMode mode in new[] { ChordMode.Ascending, ChordMode.Descending })
            foreach (int maximum in new[] { 3, 5 })
            {
                var song = Song(10000, new(60, 0, 1, 1), new(62, 0, 1, 1), new(64, 0, 1, 1),
                    new(65, 0, 1, 1), new(67, 0, 1, 1), new(62, 8000, 20, 1));
                var options = Options(true); options.InstrumentId = "piano"; options.HoldByScore = false;
                options.HoldMs = 250; options.Speed = 3; options.Chords = mode;
                options.MaxChordNotes = maximum; options.StrumMs = 150;
                var baseline = Disabled(song, options);
                var delayed = baseline.Notes.First(n => n.StartMs > 0 && n.StartMs < 1000);
                // Attack on an existing delayed key, plus a safe later source event. Do not
                // require tiny source note-off to expose a gap before the physical chord finishes.
                song.Notes.Add(new(delayed.Pitch, delayed.StartMs * options.Speed, 40, 2, 125));
                song.Notes.Add(new(72, 4000, 200, 2));
                var added = Added(song, options, GameMapping.Build(song, options), preserveAllMainFields: false);
                check(added.All(n => n.StartMs * options.Speed == 4000), "bridge invaded the original delayed chord attack/hold tail");
            }
        });
        sync("Smart interlude extremely short source notes retain fixed physical hold protection", () =>
        {
            foreach (double speed in new[] { 1, 3 })
            {
                var song = Song(10000, new(60, 0, 1, 1), new(62, 8000, 1, 1),
                    new(72, 1, 20, 2), new(74, 250 * speed - .25, 1, 2), new(76, 2000, 100, 2));
                var options = Options(true); options.InstrumentId = "piano";
                options.HoldByScore = false; options.HoldMs = 250; options.Speed = speed;
                var added = Added(song, options, GameMapping.Build(song, options), preserveAllMainFields: false);
                check(added.All(n => n.StartMs * options.Speed == 2000), "source note-off was mistaken for the end of the actual fixed key hold");
            }
        });
        sync("Smart interlude eight-ms release padding preserves adjacent same-key baseline hold and sound", () =>
        {
            foreach (double speed in new[] { .5, 1, 2, 3 })
            {
                var song = Song(5500, new(60, 0, 500, 1), new(62, 5000, 500, 1),
                    new(60, 500, 100, 2), new(60, 500 + 4 * speed, 100, 2), new(60, 500 + 12 * speed, 100, 2));
                var options = Options(true); options.InstrumentId = "piano"; options.Speed = speed;
                var baseline = Disabled(song, options); var main = baseline.Notes.Single(n => n.StartMs == 0);
                // Without the release pad, the first eligible same-key edge attack would make
                // GameMapping shorten BOTH selected HoldMs and SoundMs by 8ms. The later
                // source event is safe, so this also rejects solving the problem by banning all additions.
                double unpaddedRelease = 500 / speed - 8;
                check(unpaddedRelease < main.HoldMs && unpaddedRelease < main.SoundMs,
                    "fixture does not expose the existing same-key eight-ms release clipping");
                var plan = GameMapping.Build(song, options); var added = Added(song, options, plan);
                var retained = plan.Notes.Single(n => n.Track == 1 && n.Key == main.Key && n.StartMs == main.StartMs);
                check(retained.HoldMs == main.HoldMs && retained.SoundMs == main.SoundMs,
                    "adjacent bridge stole eight milliseconds from the selected baseline hold/sound");
                check(added.All(n => n.Key == main.Key), "same-key fixture did not exercise a real source-key handoff");
            }
        });
        sync("Smart interlude precancelled Build publishes no plan, mutates nothing and leaves later builds safe", () =>
        {
            var song = BridgeSong(); var options = Options(true); string beforeSong = Json(song), beforeOptions = Json(options);
            using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
            bool cancelled = false; PlaybackPlan? result = null;
            try { result = GameMapping.Build(song, options, cancellation.Token); } catch (OperationCanceledException) { cancelled = true; }
            check(cancelled && result == null, "cancelled arrangement returned a partial plan");
            check(beforeSong == Json(song) && beforeOptions == Json(options), "cancelled arrangement changed caller state");
            Added(song, options, GameMapping.Build(song, options));
        });
        sync("Smart interlude repeated Build keeps source note order, identities, metadata and options unchanged", () =>
        {
            var song = BridgeSong(); song.Notes.Reverse(); song.Warnings.Add("isolated fixture warning");
            var options = Options(); options.Tracks = [1, 1];
            string beforeSong = Json(song), beforeOptions = Json(options);
            var notes = song.Notes; var noteObjects = song.Notes.ToArray(); var tracks = options.Tracks;
            var first = GameMapping.Build(song, options); var second = GameMapping.Build(song, options);
            Added(song, options, first); SamePlan(second, first, "repeat arrangement");
            check(beforeSong == Json(song) && beforeOptions == Json(options), "arrangement changed source/options values or order");
            check(ReferenceEquals(notes, song.Notes) && ReferenceEquals(tracks, options.Tracks)
                && noteObjects.Select((n, i) => ReferenceEquals(n, song.Notes[i])).All(same => same), "arrangement replaced source list/events or selection");
        });
        sync("Smart interlude bounded multi-gap sample remains deterministic, source-exact and monophonic", () =>
        {
            const int blocks = 256; var notes = new List<NoteEvent>(blocks * 5);
            for (int i = 0; i < blocks; i++)
            {
                double start = i * 4000;
                notes.Add(new(60, start, 500, 1));
                notes.Add(new(64, start + 1250, 250, 2, 110));
                notes.Add(new(76, start + 1250, 250, 2, 60));
                notes.Add(new(74, start + 1300, 150, 2));
                notes.Add(new(67, start + 2700, 150, 3));
            }
            var song = Song(blocks * 4000, notes.ToArray()); var options = Options(true);
            var first = GameMapping.Build(song, options); Added(song, options, first);
            SamePlan(GameMapping.Build(song, options), first, "bounded multi-gap repeat");
            check(song.Notes.Count == blocks * 5, "bounded sample source expanded in place");
        });
    }

    private static PlayOptions Options(bool? smart = null) => new() { Tracks = [1], SmartInterludes = smart };
    private static SongDocument Song(double length, params NoteEvent[] notes) => new()
    {
        Title = "智能衔接隔离夹具（非真实歌曲）", Category = "隔离测试", Bpm = 120,
        LengthMs = length, Notes = notes.ToList(), Provenance = new() { Provider = "POP909", Synthetic = true }
    };
    private static SongDocument BridgeSong() => Song(8500,
        new(60, 0, 500, 1), new(62, 8000, 500, 1), new(72, 1500.25, 600.5, 2, 47),
        new(74, 3500, 500, 2, 111), new(67, 1500.25, 500, 3));
}
