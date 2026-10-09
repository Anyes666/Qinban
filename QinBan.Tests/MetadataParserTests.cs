using QinBan.Core;

internal static class MetadataParserTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        test("songNotes JSON preserves declared provenance and exact key timing through normalized JSON", () =>
        {
            const string text = """
                {"name":"键位元数据夹具（非歌曲）","author":"编谱者","bpm":90,"keyInstrumentId":"windsong",
                 "provenance":{"artist":"旧歌手","artists":["歌手甲","歌手乙"],"languageTags":["cmn","en"],"album":"测试专辑","versionLabel":"现场版","synthetic":true},
                 "songNotes":[{"key":"Key0","time":0,"durationMs":600},{"key":"Key1","time":850,"durationMs":150}]}
                """;
            var song = SongParser.ParseJson(text);
            check(song.Author == "编谱者" && song.Provenance.Artists.SequenceEqual(new[] { "歌手甲", "歌手乙" }) && song.Provenance.Artist == "旧歌手", "key JSON lost singers or mixed author");
            check(song.Provenance.LanguageTags.SequenceEqual(new[] { "cmn", "en" }) && song.Provenance.Album == "测试专辑" && song.Provenance.VersionLabel == "现场版" && song.Provenance.Synthetic, "key JSON lost language/version/source policy");
            var again = SongParser.ParseJson(SongParser.ToJson(song));
            check(again.Provenance.Artists.SequenceEqual(song.Provenance.Artists) && again.Provenance.LanguageTags.SequenceEqual(song.Provenance.LanguageTags) && again.Provenance.Synthetic, "normalized JSON lost key identity");
            check(song.Notes.Count == 2 && song.Notes[0].DurationMs == 600 && song.Notes[1].StartMs == 850 && song.Notes[1].DurationMs == 150, "identity changed timing");
        });
        test("songNotes JSON missing identity stays unknown and malformed provenance is rejected", () =>
        {
            const string prefix = "{\"name\":\"键位隔离夹具\",\"author\":\"作者不是歌手\",\"songNotes\":[{\"key\":\"Key0\",\"time\":0,\"durationMs\":100}]";
            var legacy = SongParser.ParseJson(prefix + "}");
            check(legacy.Provenance.Artists.Count == 0 && SongMetadata.ArtistText(legacy.Provenance) == "歌手未标注" && SongMetadata.LanguageText(legacy.Provenance) == "语种未知", "missing identity inferred");
            foreach (string provenance in new[] { "null", "{\"artists\":[null]}", "{\"artists\":[\"A\",\"A\"]}", "{\"languageTags\":[\"bad_tag\"]}" })
            {
                bool rejected = false; try { SongParser.ParseJson(prefix + ",\"provenance\":" + provenance + "}"); } catch (FormatException) { rejected = true; }
                check(rejected, "malformed key provenance silently dropped: " + provenance);
            }
        });
        test("Identity field limits count UTF16 units for supplementary characters", () =>
        {
            string character = char.ConvertFromUtf32(0x20BB7);
            var valid = new ScoreProvenance { Artists = [string.Concat(Enumerable.Repeat(character, 128))], Album = string.Concat(Enumerable.Repeat(character, 500)), VersionLabel = string.Concat(Enumerable.Repeat(character, 128)) };
            valid.Validate(); check(valid.Artists[0].Length == 256 && valid.Album.Length == 1000, "UTF16 boundary fixture wrong");
            foreach (var invalid in new[] { new ScoreProvenance { Artists = [string.Concat(Enumerable.Repeat(character, 129))] },
                new ScoreProvenance { VersionLabel = string.Concat(Enumerable.Repeat(character, 129)) }, new ScoreProvenance { Album = string.Concat(Enumerable.Repeat(character, 501)) } })
            {
                bool rejected = false; try { invalid.Validate(); } catch (FormatException) { rejected = true; }
                check(rejected, "UTF16 over-limit accepted");
            }
        });
        test("TXT separates singers/languages/album/edition from score author without guessing", () =>
        {
            var song = SongParser.ParseText("TITLE=Test fixture (not music)\nAUTHOR=Score editor\nARTISTS=First singer| Second singer\nLANGUAGES=cmn|en\nALBUM=Test album\nEDITION=Live fixture\nBPM=100\nFORMAT=keys\nA:2 S:0.5 0:1 D");
            check(song.Author == "Score editor" && song.Provenance.Artists.SequenceEqual(new[] { "First singer", "Second singer" }), "artist/author roles mixed");
            check(song.Provenance.LanguageTags.SequenceEqual(new[] { "cmn", "en" }) && song.Provenance.Album == "Test album" && song.Provenance.VersionLabel == "Live fixture", "metadata lost");
            var again = SongParser.ParseJson(SongParser.ToJson(song));
            check(again.Provenance.Artists.SequenceEqual(song.Provenance.Artists) && again.Provenance.LanguageTags.SequenceEqual(song.Provenance.LanguageTags), "JSON lost metadata");
            check(song.Notes[0].DurationMs == 1200 && song.Notes[1].DurationMs == 300 && song.Notes[2].StartMs == 2100, "metadata changed rhythm");
        });
        test("Blank TXT singer/album and und language remain honestly unknown", () =>
        {
            var song = SongParser.ParseText("TITLE=中文标题不能推断歌手语种\nAUTHOR=编配者\nARTISTS=\nLANGUAGES=und\nALBUM=\nEDITION=\nA S D");
            check(song.Provenance.Artists.Count == 0 && SongMetadata.ArtistText(song.Provenance).Contains("未标注"), "author used as singer");
            check(SongMetadata.LanguageText(song.Provenance).Contains("未知") && !SongMetadata.HasRequiredIdentity(song.Provenance), "unknown language certified");
        });
        test("TXT malformed or duplicate multi-value identity headers are rejected", () =>
        {
            foreach (string header in new[] { "ARTISTS=A||B", "ARTISTS=A|A", "LANGUAGES=cmn|cmn", "LANGUAGES=bad_tag", "LANGUAGES=cmn||en" })
            {
                bool rejected = false; try { SongParser.ParseText(header + "\nA S D"); } catch (FormatException) { rejected = true; }
                check(rejected, "invalid header accepted: " + header);
            }
        });
    }
}
