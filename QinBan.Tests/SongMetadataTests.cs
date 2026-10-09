using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using QinBan.Core;

static class SongMetadataTests
{
    public static void Run(string fixtures, Action<string, Action> sync, Action<bool, string> check)
    {
        var utf8 = new UTF8Encoding(false);
        string NewRoot()
        {
            string root = Path.Combine(fixtures, "song-metadata-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root); return root;
        }
        SongDocument Sample() => new()
        {
            Title = "元数据隔离夹具（非真实歌曲）", Author = "编谱者甲", Category = "隔离测试",
            Notes = [new(60, 0, 100), new(64, 250, 100)],
            Provenance = new() { Synthetic = true, Artist = "旧歌手", Artists = ["歌手甲", "歌手乙"],
                LanguageTags = ["cmn", "en-US"], Album = "星光专辑", VersionLabel = "现场版" }
        };
        (LibraryStore Store, string Root, string Catalog, LibraryEntry Entry) Fixture()
        {
            string root = NewRoot(), songs = Path.Combine(root, "catalog-resources"); Directory.CreateDirectory(songs);
            var song = Sample(); string resource = Path.Combine(songs, "fixture.json");
            File.WriteAllText(resource, SongParser.ToJson(song), utf8);
            var entry = LibraryStore.Create(song, "fixture.json", LibraryCatalog.HashFile(resource), true);
            entry.Id = entry.CatalogId = "metadata:fixture";
            string catalog = Path.Combine(songs, LibraryCatalog.FileName);
            LibraryCatalog.Build(catalog, [entry], songs);
            return (new LibraryStore(Path.Combine(root, "isolated-state"), songs), root, catalog, entry);
        }
        bool Rejected(Action action)
        {
            try { action(); return false; } catch (FormatException) { return true; }
        }
        void Reject(ScoreProvenance provenance, string why)
        {
            check(Rejected(provenance.Validate), "validation accepted " + why);
            var song = Sample(); song.Provenance = provenance;
            check(Rejected(() => SongParser.ParseJson(JsonSerializer.Serialize(song, JsonDefaults.Options))), "JSON accepted " + why);
            check(Rejected(() => LibrarySearch.Build(new() { Title = "隔离校验", Provenance = provenance })), "search accepted " + why);
        }
        void Search(LibraryStore store, string id, params string[] terms)
        {
            foreach (string term in terms)
            {
                var page = store.Query(new(Search: term));
                check(page.Total == 1 && page.Items.Single().Id == id, "metadata search mismatch: " + term);
            }
        }
        string SchemaText(string path)
        {
            using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
                { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name";
            using var reader = command.ExecuteReader(); var rows = new List<string>();
            while (reader.Read()) rows.Add(reader.GetString(0) + "|" + reader.GetString(1) + "|" + reader.GetString(2));
            return string.Join("\n", rows);
        }

        sync("Metadata legacy JSON defaults stay unknown and retain legacy Artist and Author", () =>
        {
            const string old = """
                {"title":"English 中文 日本語 제목","author":"作者不是歌手","notes":[{"pitch":60,"startMs":0,"durationMs":100}]}
                """;
            var song = SongParser.ParseJson(old); var provenance = song.Provenance;
            check(provenance.Artists.Count == 0 && provenance.LanguageTags.Count == 0 && provenance.Album == "" && provenance.VersionLabel == "" && provenance.RightsStatus == "", "legacy defaults changed");
            check(SongMetadata.ArtistText(provenance) == "歌手未标注" && SongMetadata.LanguageText(provenance) == "语种未知", "title/author inferred metadata");
            var entry = LibraryStore.Create(song, "fixture.json", "hash", false);
            check(entry.Author == "作者不是歌手" && entry.ArtistText == "歌手未标注", "author was treated as singer");
            check(entry.Detail == $"{entry.Author}  ·  {entry.Category}  ·  {entry.Bpm:0} BPM", "legacy Detail changed");
            provenance = JsonSerializer.Deserialize<ScoreProvenance>("{\"artist\":\"旧歌手\"}", JsonDefaults.Options)!;
            provenance.Validate(); check(SongMetadata.ArtistText(provenance) == "旧歌手", "legacy Artist fallback lost");
            provenance.Artists = ["新歌手甲", "新歌手乙"];
            check(SongMetadata.ArtistText(provenance) == "新歌手甲 / 新歌手乙" && provenance.Artist == "旧歌手", "list precedence mutated legacy Artist");
            provenance.Artists = []; provenance.Artist = " ";
            check(SongMetadata.ArtistText(provenance) == "歌手未标注", "blank legacy Artist not unknown");
            var legacyEntry = JsonSerializer.Deserialize<LibraryEntry>("{\"title\":\"旧目录\",\"author\":\"编谱者\",\"provenance\":{}}", JsonDefaults.Options)!;
            check(legacyEntry.ArtistText == "歌手未标注" && legacyEntry.LanguageText == "语种未知", "old catalog JSON defaults lost");
        });
        sync("Metadata multiple artists and languages round-trip without serializing UI getters", () =>
        {
            var song = Sample(); song.Provenance.RightsStatus = "candidate-unverified";
            var roundTrip = SongParser.ParseJson(SongParser.ToJson(song)); var copy = song.Copy();
            foreach (var result in new[] { roundTrip, copy })
            {
                check(result.Provenance.Artists.SequenceEqual(song.Provenance.Artists) && result.Provenance.LanguageTags.SequenceEqual(song.Provenance.LanguageTags), "list round-trip lost order/content");
                check(result.Author == song.Author && result.Provenance.Artist == "旧歌手" && result.Provenance.Album == "星光专辑" && result.Provenance.VersionLabel == "现场版", "scalar metadata changed");
                check(result.Provenance.RightsStatus == "candidate-unverified", "rights status JSON/copy round-trip lost value");
            }
            copy.Provenance.Artists.Add("其他歌手"); copy.Provenance.LanguageTags.Add("ja");
            check(song.Provenance.Artists.Count == 2 && song.Provenance.LanguageTags.Count == 2, "Copy shares metadata lists");
            var entry = LibraryStore.Create(roundTrip, "fixture.json", "hash", true);
            check(entry.ArtistText == "歌手甲 / 歌手乙" && entry.LanguageText == "国语 / 英语", "display order/labels");
            check(entry.MetadataText == "歌手甲 / 歌手乙 · 国语 / 英语 · 现场版", "UI metadata combination");
            using var json = JsonDocument.Parse(JsonSerializer.Serialize(entry, JsonDefaults.Options));
            foreach (string name in new[] { "artistText", "languageText", "metadataText" })
                check(!json.RootElement.TryGetProperty(name, out _), "computed UI metadata leaked into JSON: " + name);
            entry.Provenance.VersionLabel = "";
            check(entry.MetadataText == "歌手甲 / 歌手乙 · 国语 / 英语", "blank version leaves a separator");
        });
        sync("Metadata language labels cover unknown valid tags and instrumental without guessing", () =>
        {
            foreach (var (tag, label) in new[] { ("cmn", "国语"), ("zh", "中文（未细分）"), ("ZH-Hans-CN", "中文（未细分）"), ("zh-Hant", "中文（未细分）"),
                ("yue", "粤语"), ("EN-us", "英语"), ("ja", "日语"), ("ko", "韩语"),
                ("zxx", "纯音乐（无歌词）"), ("und", "语种未知"), ("fr-CA", "fr-CA"), ("zz-Abcd-123", "zz-Abcd-123") })
            {
                var p = new ScoreProvenance { LanguageTags = [tag] }; p.Validate();
                check(SongMetadata.LanguageText(p) == label, "language label: " + tag);
            }
            check(SongMetadata.LanguageText(new()) == "语种未知", "missing language not unknown");
            check(SongMetadata.LanguageText(new() { LanguageTags = ["yue", "ja", "ko", "fr-CA", "zxx", "und"] })
                == "粤语 / 日语 / 韩语 / fr-CA / 纯音乐（无歌词） / 语种未知", "multiple-language join/order");
        });
        sync("Metadata validates exact size boundaries", () =>
        {
            var p = new ScoreProvenance { Artists = Enumerable.Range(0, 32).Select(i => "歌手" + i).ToList(),
                LanguageTags = Enumerable.Range(0, 16).Select(i => "qaa-" + i).ToList(), Album = new string('专', 1000), VersionLabel = new string('版', 256) };
            p.Artists[0] = new string('歌', 256); p.LanguageTags[0] = "abcd" + string.Concat(Enumerable.Repeat("-abcdefgh", 28));
            p.Validate(); var song = Sample(); song.Provenance = p;
            var parsed = SongParser.ParseJson(SongParser.ToJson(song));
            check(parsed.Provenance.Artists.Count == 32 && parsed.Provenance.Artists[0].Length == 256 && parsed.Provenance.LanguageTags.Count == 16
                && parsed.Provenance.LanguageTags[0].Length == 256 && parsed.Provenance.Album.Length == 1000 && parsed.Provenance.VersionLabel.Length == 256, "exact limits rejected/lost");
        });
        sync("Metadata formal-song declarations require singer and explicit non-und language, not new certification", () =>
        {
            var formal = new ScoreProvenance { RedistributionVerified = true, Completeness = "full-work", TimingStatus = "source-compared",
                MusicReview = "human-reviewed", GameReview = "verified-arrangement" };
            string status = formal.StatusText;
            check(!SongMetadata.HasRequiredIdentity(formal) && !formal.IsFormalSong, "missing identity accepted as formal");
            formal.Artists = ["歌手"];
            check(!SongMetadata.HasRequiredIdentity(formal) && !formal.IsFormalSong, "missing language accepted as formal");
            formal.LanguageTags = ["zh"]; formal.Validate();
            check(SongMetadata.HasRequiredIdentity(formal) && formal.IsFormalSong, "complete declared identity rejected");
            check(formal.StatusText == status, "identity changed status/certification text");
            foreach (var tags in new List<string>[] { ["und"], ["UND"], ["en", "und"], ["en", "UND-Latn"], ["en_US"], [null!], [], null! })
            {
                formal.LanguageTags = tags;
                check(!SongMetadata.HasRequiredIdentity(formal) && !formal.IsFormalSong, "unknown/invalid language accepted as formal");
            }
            formal.LanguageTags = ["zxx"]; formal.Validate();
            check(SongMetadata.HasRequiredIdentity(formal) && formal.IsFormalSong, "explicit instrumental language rejected");
            formal.Artists = []; formal.Artist = "历史歌手"; formal.LanguageTags = ["yue"]; formal.Validate();
            check(SongMetadata.HasRequiredIdentity(formal) && formal.IsFormalSong, "legacy Artist plus language rejected");
            formal.Artist = " ";
            check(!SongMetadata.HasRequiredIdentity(formal) && !formal.IsFormalSong, "blank legacy Artist accepted as identity");
            formal.Artists = ["歌手"]; formal.LanguageTags = ["en"]; formal.Synthetic = true;
            check(!formal.IsFormalSong && !Sample().Provenance.IsFormalSong, "self-made fixture counted as formal song");
            var declaration = new ScoreProvenance { Artists = ["歌手"], LanguageTags = ["zh"] };
            check(SongMetadata.HasRequiredIdentity(declaration) && !declaration.IsFormalSong && declaration.StatusText == "个人谱 · 待核验", "identity alone certified an unreviewed declaration");
        });
        sync("Metadata rejects null, empty, duplicate, oversized and malformed fields through real parser/search", () =>
        {
            foreach (var artists in new List<string>[] { null!, [null!], [""], [" \t"], [new string('\u6b4c', 257)],
                ["\u6b4c\u624b", "\u6b4c\u624b"], ["Singer", "singer"], ["\u6b4c\u624b", " \u6b4c\u624b "], Enumerable.Range(0, 33).Select(i => "\u6b4c\u624b" + i).ToList() })
                Reject(new() { Artists = artists }, "artists");
            foreach (var tags in new List<string>[] { null!, [null!], [""], [" "], ["en", "en"], ["en", "EN"],
                Enumerable.Range(0, 17).Select(i => "qaa-" + i).ToList() }) Reject(new() { LanguageTags = tags }, "language list");
            foreach (string tag in new[] { "en_US", "\u56fd\u8bed", "e", "123", "abcdefghi", "-en", "en-", "en--US", "en-abcdefghi", "en US", "en/ja", "en\n",
                "abcde" + string.Concat(Enumerable.Repeat("-abcdefgh", 28)) }) Reject(new() { LanguageTags = [tag] }, "language tag " + tag);
            Reject(new() { Album = null! }, "null album");
            Reject(new() { VersionLabel = null! }, "null version");
            Reject(new() { VersionLabel = new string('\u7248', 257) }, "long version");
            Reject(new() { RightsStatus = new string('a', 65) }, "long rights status");
            Reject(new() { RightsStatus = "candidate unverified" }, "rights status with space");
            Reject(new() { RightsStatus = "-invalid" }, "rights status with invalid prefix");
            new ScoreProvenance().Validate();
            new ScoreProvenance { RightsStatus = "candidate-unverified" }.Validate();
        });
        sync("Metadata real read-only catalogue supports combined text, raw tags, labels, pinyin and initials", () =>
        {
            var (store, _, catalog, entry) = Fixture(); string hash = LibraryCatalog.HashFile(catalog), schema = SchemaText(catalog);
            check(store.SongReads == 0, "catalogue startup read scores");
            Search(store, entry.Id, "歌手甲 cmn", "歌手乙 en-US", "国语 英语", "旧歌手 星光专辑 现场版", "编谱者甲 歌手乙",
                "geshoujia yingyu xingguangzhuanji xianchangban", "gsj yy xgzj xcb", "歌手乙 yingyu xgzj 现场版");
            check(store.Query(new(Search: "歌手甲 粤语")).Total == 0, "combination was OR instead of AND");
            check(store.SongReads == 0, "metadata search parsed scores");
            var found = store.Find(entry.Id)!; found.Favorite = true; found.InQueue = true; found.Options.Speed = 1.25; store.Save(found);
            var reopened = new LibraryStore(store.DataDirectory, store.BuiltInDirectory); var restored = reopened.Find(entry.Id)!;
            check(restored.ArtistText == "歌手甲 / 歌手乙" && restored.LanguageText == "国语 / 英语" && restored.Favorite && restored.InQueue && restored.Options.Speed == 1.25, "catalogue restart lost metadata/user state");
            check(reopened.LoadSong(restored).Provenance.LanguageTags.SequenceEqual(new[] { "cmn", "en-US" }), "resource metadata lost");
            Search(reopened, entry.Id, "gsj yy xgzj xcb");
            using var readOnly = new SqliteConnection(new SqliteConnectionStringBuilder
                { DataSource = catalog, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            readOnly.Open(); using var command = readOnly.CreateCommand(); command.CommandText = "UPDATE meta SET value='bad' WHERE key='schema'";
            bool blocked = false; try { command.ExecuteNonQuery(); } catch (SqliteException ex) when (ex.SqliteErrorCode == 8) { blocked = true; }
            check(blocked, "read-only catalogue allowed a write");
            check(hash == LibraryCatalog.HashFile(catalog) && schema == SchemaText(catalog), "catalogue bytes/schema changed");
            check(reopened.Statistics().FormalSongs == 0, "synthetic catalogue counted as songs");
        });
        sync("Metadata real LibraryStore import and restart persist new and legacy JSON without schema changes", () =>
        {
            var (store, root, catalog, _) = Fixture(); string catalogHash = LibraryCatalog.HashFile(catalog), schema = SchemaText(store.DatabasePath);
            var song = Sample(); song.Title = "导入隔离夹具（非真实歌曲）"; song.Author = "编谱者乙";
            song.Provenance.Artist = "历史歌手"; song.Provenance.Artists = ["云舟甲", "云舟乙"];
            song.Provenance.LanguageTags = ["yue", "ja", "fr-CA"]; song.Provenance.Album = "远行专辑"; song.Provenance.VersionLabel = "新版";
            string source = Path.Combine(root, "import-source.json"); File.WriteAllText(source, SongParser.ToJson(song), utf8);
            string sourceHash = LibraryCatalog.HashFile(source); var imported = store.Import(source);
            check(!imported.Duplicate && !imported.Entry.BuiltIn && imported.Entry.Author == "编谱者乙", "import failed/changed author");
            check(store.Import(source).Duplicate && store.Count == 2, "duplicate import created an entry");
            Search(store, imported.Entry.Id, "云舟甲 粤语 日语 fr-CA 远行专辑 新版", "yunzhoujia yueyu riyu yuanxingzhuanji xinban", "yzj yy ry yxzj xb", "云舟乙 ja 历史歌手");
            const string old = """
                {"title":"旧格式隔离夹具","author":"作者不是歌手","provenance":{"synthetic":true},"notes":[{"pitch":60,"startMs":0,"durationMs":100}]}
                """;
            string legacySource = Path.Combine(root, "legacy-source.json"); File.WriteAllText(legacySource, old, utf8);
            string legacyHash = LibraryCatalog.HashFile(legacySource); var legacy = store.Import(legacySource).Entry;
            var reopened = new LibraryStore(store.DataDirectory, store.BuiltInDirectory); var restored = reopened.Find(imported.Entry.Id)!;
            check(restored.Provenance.Artists.SequenceEqual(song.Provenance.Artists) && restored.Provenance.LanguageTags.SequenceEqual(song.Provenance.LanguageTags)
                && restored.Provenance.Album == "远行专辑" && restored.Provenance.VersionLabel == "新版" && restored.Provenance.Artist == "历史歌手", "database restart lost metadata");
            check(reopened.LoadSong(restored).Provenance.Artists.SequenceEqual(song.Provenance.Artists), "normalized score lost artists");
            var oldEntry = reopened.Find(legacy.Id)!;
            check(oldEntry.ArtistText == "歌手未标注" && oldEntry.LanguageText == "语种未知" && oldEntry.Provenance.Album == "" && oldEntry.Provenance.VersionLabel == "", "legacy import/restart inferred metadata");
            Search(reopened, restored.Id, "yzj yy ry yxzj xb", "云舟甲 fr-CA 新版");
            check(sourceHash == LibraryCatalog.HashFile(source) && legacyHash == LibraryCatalog.HashFile(legacySource), "source files were changed");
            check(catalogHash == LibraryCatalog.HashFile(catalog) && schema == SchemaText(reopened.DatabasePath), "import changed catalogue/schema");
            check(reopened.Count == 3 && reopened.Statistics().FormalSongs == 0, "self-made imports counted as formal songs");
        });
        sync("Metadata songNotes real import retains identity and source safety across restart", () =>
        {
            var (store, root, catalog, _) = Fixture(); string catalogHash = LibraryCatalog.HashFile(catalog);
            const string text = """
                {"name":"键位导入隔离夹具（非歌曲）","author":"键位编谱者","bpm":100,
                 "provenance":{"synthetic":true,"artist":"旧歌手","artists":["键位歌手甲","键位歌手乙"],"languageTags":["cmn","en"],"album":"键位专辑","versionLabel":"键位测试版"},
                 "songNotes":[{"key":"Key0","time":0,"durationMs":600},{"key":"Key1","time":850,"durationMs":150}]}
                """;
            string source = Path.Combine(root, "key-source.json"); File.WriteAllText(source, text, utf8); string sourceHash = LibraryCatalog.HashFile(source);
            var imported = store.Import(source); check(!imported.Duplicate && imported.Entry.Author == "键位编谱者", "key import failed/changed author");
            var reopened = new LibraryStore(store.DataDirectory, store.BuiltInDirectory); var entry = reopened.Find(imported.Entry.Id)!;
            Search(reopened, entry.Id, "键位歌手甲 国语 英语 键位专辑 键位测试版", "键位歌手乙 cmn 旧歌手");
            var song = reopened.LoadSong(entry);
            check(song.Provenance.Artists.SequenceEqual(new[] { "键位歌手甲", "键位歌手乙" }) && song.Provenance.Synthetic
                && song.Notes[0].DurationMs == 600 && song.Notes[1].StartMs == 850 && song.Notes[1].DurationMs == 150, "normalized import lost key identity/timing/policy");
            check(sourceHash == LibraryCatalog.HashFile(source) && catalogHash == LibraryCatalog.HashFile(catalog), "key import modified original/read-only catalogue");
            check(reopened.Statistics().FormalSongs == 0, "synthetic key import counted as real songs");
        });
        sync("Metadata invalid real imports preserve originals and roll back isolated state", () =>
        {
            var (store, root, catalog, _) = Fixture(); string hash = LibraryCatalog.HashFile(catalog);
            foreach (var p in new ScoreProvenance[] { new() { Artists = [null!] }, new() { LanguageTags = ["zh_CN"] },
                new() { Album = null! }, new() { VersionLabel = new string('版', 257) } })
            {
                var song = Sample(); p.Synthetic = true; song.Provenance = p;
                string source = Path.Combine(root, Guid.NewGuid().ToString("N") + ".json");
                File.WriteAllText(source, JsonSerializer.Serialize(song, JsonDefaults.Options), utf8); string originalHash = LibraryCatalog.HashFile(source);
                check(Rejected(() => store.Import(source)), "invalid metadata import succeeded");
                check(File.Exists(source) && originalHash == LibraryCatalog.HashFile(source), "invalid source removed/changed");
                check(store.Count == 1 && Directory.GetFiles(Path.Combine(store.DataDirectory, "scores")).Length == 0
                    && Directory.GetFiles(Path.Combine(store.DataDirectory, "originals")).Length == 0, "invalid import left partial state");
            }
            check(hash == LibraryCatalog.HashFile(catalog), "invalid import touched catalogue");
        });
    }
}
