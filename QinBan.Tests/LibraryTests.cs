using System.Text.Json;
using QinBan.Core;
using Microsoft.Data.Sqlite;

static class LibraryTests
{
    public static void Run(string fixtures, string repo, Action<string, Action> test, Action<bool, string> check, Action<Action> throws)
    {
        string NewRoot() { string root = Path.Combine(fixtures, "library-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root); return root; }
        (LibraryStore Store, string Root, string Catalog) Fixture(int count = 130)
        {
            string root = NewRoot(), songs = Path.Combine(root, "Songs"); Directory.CreateDirectory(songs);
            var song = new SongDocument { Title = "合成测试夹具（不是歌曲）", Notes = [new(60, 0, 100), new(64, 250, 500)], Provenance = new() { Synthetic = true } };
            string resource = Path.Combine(songs, "fixture.json"); File.WriteAllText(resource, SongParser.ToJson(song, false)); string hash = LibraryCatalog.HashFile(resource);
            var entries = Enumerable.Range(0, count).Select(i => new LibraryEntry
            {
                Id = "test:" + i.ToString("D4"), CatalogId = "test:" + i.ToString("D4"), BuiltIn = true,
                RelativePath = "fixture.json", Hash = hash, ResourceHash = hash,
                Title = i == 3 ? "星光练习" : i == 5 ? "大众优先标题（未标语种）" : "测试谱 " + i.ToString("D4"), Author = i % 2 == 0 ? "作者甲" : "作者乙",
                DurationMs = (i % 5 + 1) * 1000, Bpm = 100, NotesCount = 2, AddedAt = DateTimeOffset.UnixEpoch.AddMilliseconds(i),
                Provenance = new() { Synthetic = true, WorkId = "work:" + i / 2, Artist = "演奏者乙", Aliases = i == 3 ? ["Starlight", "星光別名", "chongqing"] : [],
                    TimingStatus = i % 2 == 0 ? "source-compared" : "unverified", MusicReview = i % 3 == 0 ? "human-reviewed" : "not-reviewed", Completeness = "exercise",
                    LanguageTags = i is 3 or 4 ? ["zh"] : i == 7 ? ["cmn"] : [],
                    Tags = i == 3 ? ["中文歌曲", "中文流行候选"] : i == 4 ? ["中文歌曲", "中文流行", "大众优先"] : i == 6 ? ["大众优先"] : [] }
            }).ToList();
            string catalog = Path.Combine(songs, LibraryCatalog.FileName); LibraryCatalog.Build(catalog, entries, syntheticOnly: true);
            return (new LibraryStore(Path.Combine(root, "UserData"), songs), root, catalog);
        }
        test("SQLite Chinese, pinyin, initials, alias, traditional and combination search", () =>
        {
            var (store, _, _) = Fixture();
            foreach (string term in new[] { "星", "星光", "星光練習", "xingguang", "xglx", "Starlight", "星光别名", "chongqing", "星光 作者乙", "星光 演奏者乙", "XINGGUANG" })
            {
                var page = store.Query(new(Search: term)); check(page.Total == 1 && page.Items[0].Title == "星光练习", "missing: " + term);
            }
            check(store.Query(new(Search: "not-found")).Total == 0, "empty result");
            foreach (string term in new[] { "' OR 1=1 --", "%", "___", "; DROP TABLE entries;", "😀" }) check(store.Query(new(Search: term)).Total == 0, "unsafe/special term");
            throws(() => store.Query(new(Search: new string('x', 513))));
            throws(() => store.Query(new(Search: string.Join(' ', Enumerable.Range(0, 17)))));
            check(store.Query(new()).Total == 130, "special search modified database");
        });
        test("Chinese-pop candidate and explicit popular-main filters keep metadata boundaries", () =>
        {
            var (store, _, _) = Fixture();
            var candidates = store.Query(new(Filter: LibraryFilter.ChinesePop));
            var popular = store.Query(new(Filter: LibraryFilter.ChinesePopular));
            check(candidates.Total == 3 && candidates.Items.Any(e => e.Id == "test:0007") && popular.Total > 0 && candidates.Total >= popular.Total, "Chinese-pop candidate/main relationship");
            check(popular.Items.All(e => e.Provenance.Tags.Contains("大众优先")
                && e.Provenance.Tags.Any(tag => tag is "中文歌曲" or "中文流行" or "中文流行候选" or "粤语歌曲" or "粤语流行" or "粤语流行候选")),
                "popular-main requires explicit priority and Chinese/Cantonese tags");
            check(!popular.Items.Any(e => e.Id is "test:0005" or "test:0006"), "popular-main inferred title or unmarked language");
             var unknown = store.Query(new(Filter: LibraryFilter.UnknownLanguage));
             check(unknown.Total == 127 && unknown.Items.All(e => e.Provenance.LanguageTags.Count == 0
                 || e.Provenance.LanguageTags.All(tag => tag.StartsWith("und", StringComparison.OrdinalIgnoreCase)
                     || tag.StartsWith("unknown", StringComparison.OrdinalIgnoreCase)
                     || tag.StartsWith("unspecified", StringComparison.OrdinalIgnoreCase))),
                 "unknown-language filter keeps missing/explicit unknown tags only");
            var recommended = store.Query(new(Sort: LibrarySort.ChinesePopular, Limit: 4));
            check(recommended.Items.Take(2).Select(e => e.Id).SequenceEqual(new[] { "test:0004", "test:0003" }), "Chinese recommendation tier order");
            check(store.Query(new(Sort: LibrarySort.ChinesePopular)).Total == 130, "Chinese sort preserves total");
        });
        test("Language summary counts explicit tags without treating missing language as English", () =>
        {
            var (store, _, _) = Fixture();
            var summary = store.LanguageSummary();
            check(summary.Total == 130 && summary.ChinesePop == 3 && summary.ChinesePopular == 1
                && summary.ExplicitEnglish == 0 && summary.UnknownLanguage == 127,
                $"unexpected language summary: total={summary.Total}, chinese={summary.ChinesePop}, popular={summary.ChinesePopular}, english={summary.ExplicitEnglish}, unknown={summary.UnknownLanguage}");
        });        test("SQLite paging is stable and no rows disappear or repeat under all sorts", () =>
        {
            var (store, _, _) = Fixture();
            foreach (LibrarySort sort in Enum.GetValues<LibrarySort>())
            {
                var ids = new List<string>(); for (int offset = 0; offset < 130; offset += 17) ids.AddRange(store.Query(new(Sort: sort, Offset: offset, Limit: 17)).Items.Select(e => e.Id));
                check(ids.Count == 130 && ids.Distinct().Count() == 130, "page duplicates / omissions");
                check(ids.SequenceEqual(store.Enumerate(new(Sort: sort)).Select(e => e.Id)), "unstable ordering");
                var selected = store.Find(ids[78])!;
                check(store.FindPosition(new(Sort: sort, Limit: 17), selected) == 78 && store.FindOffset(new(Sort: sort, Limit: 17), selected) == 68, "cross-page position");
            }
            check(store.Query(new(Offset: 999)).Items.Count == 0, "out-of-range not empty");
            throws(() => store.Query(new(Offset: -1))); throws(() => store.Query(new(Limit: 1001)));
        });
        test("Read-only catalogue, lazy score reads and integrity rejection", () =>
        {
            var (store, _, catalog) = Fixture(); string before = LibraryCatalog.HashFile(catalog);
            check(store.SongReads == 0, "eager startup score read"); _ = store.Query(new(Search: "星")); check(store.SongReads == 0, "search reads scores");
            var entry = store.Find("test:0003")!; _ = store.LoadSong(entry); check(store.SongReads == 1, "selected score not counted");
            entry.Favorite = true; entry.InQueue = true; entry.Options.Speed = 1.25; store.Save(entry);
            check(before == LibraryCatalog.HashFile(catalog), "catalogue was modified by user state");
            File.AppendAllText(store.ResolvePath(entry), " "); throws(() => store.LoadSong(entry)); check(store.SongReads == 1, "failed integrity read counted");
            check(File.Exists(store.ResolvePath(entry)), "bad resource deleted");
        });
        test("Filters and work grouping keep quality claims separate from formal songs", () =>
        {
            var (store, _, _) = Fixture();
            check(store.Query(new(Filter: LibraryFilter.BuiltIn)).Total == 130 && store.Query(new(Filter: LibraryFilter.Personal)).Total == 0, "source filters");
            check(store.Query(new(Quality: LibraryQuality.TimingCompared)).Total == 65, "timing filter");
            check(store.Query(new(Quality: LibraryQuality.NotHumanReviewed)).Total == 86, "human review filter");
            check(store.Query(new(Quality: LibraryQuality.Exercises)).Total == 130, "exercise filter");
            check(store.Query(new(WorkId: "work:1")).Total == 2, "work editions");
            check(store.Statistics().Works == 65 && store.Statistics().FormalSongs == 0, "synthetic counted as formal song");
            var e = store.Find("test:0003")!; e.LastPlayedAt = DateTimeOffset.UtcNow; store.Save(e);
            check(store.Query(new(Filter: LibraryFilter.Recent)).Total == 1, "recent filter");
            check(new ScoreProvenance { Provider = "mutopia" }.StatusText.Contains("待核验"), "provider alone claimed timing verification");
        });
        test("Atomic SaveMany rolls back persisted and observed state after mid-batch failure", () =>
        {
            var (store, _, _) = Fixture(); var a = store.Find("test:0000")!; var b = store.Find("test:0001")!;
            a.Favorite = b.Favorite = true; b.Options.Speed = -1;
            throws(() => store.SaveMany([a, b]));
            check(!a.Favorite && !b.Favorite && b.Options.Speed == 1, "observed state not restored");
            check(new LibraryStore(store.DataDirectory, store.BuiltInDirectory).Query(new(Favorites: true)).Total == 0, "partial commit");
            a.Favorite = b.Favorite = true; a.InQueue = true; store.SaveMany([a, b, a]);
            var reopened = new LibraryStore(store.DataDirectory, store.BuiltInDirectory);
            check(reopened.Query(new(Favorites: true)).Total == 2 && reopened.Query(new(Queue: true)).Total == 1, "batch state lost");
        });
        test("Playlists persist, reject duplicate names, preserve order and never delete scores", () =>
        {
            var (store, _, catalog) = Fixture(); var a = store.Find("test:0003")!; var b = store.Find("test:0001")!; var c = store.Find("test:0002")!;
            var list = store.CreatePlaylist("  我的歌单  "); throws(() => store.CreatePlaylist("我的歌单")); throws(() => store.CreatePlaylist(" "));
            store.AddToPlaylist(list.Id, [a, b, a]); store.AddToPlaylist(list.Id, [c]);
            var reopened = new LibraryStore(store.DataDirectory, store.BuiltInDirectory);
            check(reopened.Query(new(PlaylistId: list.Id)).Items.Select(e => e.Id).SequenceEqual(new[] { a.Id, b.Id, c.Id }), "playlist order / dedup / reopen");
            store.RenamePlaylist(list.Id, "重新命名"); check(store.Playlists().Single().Name == "重新命名", "rename failed");
            var invalid = new LibraryEntry { Id = "missing", CatalogId = "missing" }; var fresh = store.CreatePlaylist("事务测试");
            throws(() => store.AddToPlaylist(fresh.Id, [a, invalid])); check(store.Query(new(PlaylistId: fresh.Id)).Total == 0, "partial playlist add");
            store.RemoveFromPlaylist(list.Id, [b]); check(store.Playlists().First(p => p.Id == list.Id).Count == 2, "remove item");
            string before = LibraryCatalog.HashFile(catalog); store.DeletePlaylist(list.Id); store.DeletePlaylist(fresh.Id);
            check(store.Playlists().Count == 0 && store.Count == 130 && before == LibraryCatalog.HashFile(catalog), "delete touched songs");
        });
        test("Legacy JSON copies exactly once and preserves originals, IDs, flags, options and retired entries", () =>
        {
            string root = NewRoot(), data = Path.Combine(root, "旧数据"), songs = Path.Combine(repo, "Songs"); Directory.CreateDirectory(Path.Combine(data, "scores"));
            string personal = Path.Combine(data, "scores", "old.json"); File.WriteAllText(personal, SongParser.ToJson(new SongDocument { Title = "迁移个人谱", Notes = [new(60,0,100)] }, false));
            string bg = Path.Combine(data, "background.jpg"); File.WriteAllBytes(bg, [1, 2, 3]);
            var oldBuiltin = LibraryStore.Create(SongParser.Read(Path.Combine(songs,"01.json")), "01.json", LibraryCatalog.HashFile(Path.Combine(songs,"01.json")), true);
            oldBuiltin.Id = "old-built-in-id"; oldBuiltin.Favorite = oldBuiltin.InQueue = true; oldBuiltin.Options.Speed = 1.5; oldBuiltin.LastPlayedAt = DateTimeOffset.UtcNow;
            var oldPersonal = LibraryStore.Create(SongParser.Read(personal), "scores/old.json", LibraryCatalog.HashFile(personal), false); oldPersonal.Id = "old-user-id";
            oldPersonal.Favorite = true; oldPersonal.Options.Transpose = 2;
            var retired = LibraryStore.Create(SongParser.Read(Path.Combine(songs,"01.json")), "retired.json", "oldhash", true); retired.Id = "old-retired";
            string legacy = Path.Combine(data, "library.json"); File.WriteAllText(legacy, JsonSerializer.Serialize(new[] { oldBuiltin, oldPersonal, retired }, JsonDefaults.Options));
            string legacyHash = LibraryCatalog.HashFile(legacy), personalHash = LibraryCatalog.HashFile(personal), bgHash = LibraryCatalog.HashFile(bg);
            var store = new LibraryStore(data, songs);
            int builtinCount = Directory.GetFiles(songs, "*.json").Length;
            check(store.MigratedLegacy && store.Count == builtinCount + 1 && Directory.GetFiles(data,"*.bak").Length == 1, "migration counts / backup");
            var migrated = store.Find(oldBuiltin.Id)!; check(migrated.Favorite && migrated.InQueue && migrated.Options.Speed == 1.5 && migrated.LastPlayedAt != null, "builtin ID/state lost");
            check(store.Find(oldPersonal.Id)!.Options.Transpose == 2, "personal ID/options lost");
            check(store.LoadWarnings.Any(w => w.Contains("old") || w.Contains("保留")), "retired not reported");
            using (var connection = new SqliteConnection("Data Source=" + store.DatabasePath)) { connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT count(*) FROM retired_legacy"; check(Convert.ToInt32(command.ExecuteScalar()) == 1, "retired state lost"); }
            check(!new LibraryStore(data,songs).MigratedLegacy && Directory.GetFiles(data,"*.bak").Length == 1, "migration repeated");
            check(legacyHash == LibraryCatalog.HashFile(legacy) && personalHash == LibraryCatalog.HashFile(personal) && bgHash == LibraryCatalog.HashFile(bg), "legacy resources modified");
        });
        test("Damaged legacy JSON and database are never cleared or silently replaced", () =>
        {
            string root = NewRoot(), data = Path.Combine(root,"UserData"); Directory.CreateDirectory(data); string json = Path.Combine(data,"library.json"); File.WriteAllText(json,"invalid");
            string hash = LibraryCatalog.HashFile(json); throws(() => new LibraryStore(data,Path.Combine(repo,"Songs"))); check(hash == LibraryCatalog.HashFile(json), "bad JSON replaced");
            string damaged = Path.Combine(NewRoot(),"library.db"); File.WriteAllBytes(damaged,[1,2,3,4,5]); hash = LibraryCatalog.HashFile(damaged);
            throws(() => new LibraryStore(Path.GetDirectoryName(damaged)!,Path.Combine(repo,"Songs"))); check(hash == LibraryCatalog.HashFile(damaged), "bad database replaced");
        });
        test("Catalogue paths cannot escape resource root", () =>
        {
            foreach (string path in new[] { "../outside.json", "..\\outside.json", "C:\\outside.json", "\\\\server\\share\\score.json" }) throws(() => LibraryCatalog.Resolve(fixtures,path));
        });
        test("Synthetic metadata or document cannot emit real-game input", () =>
        {
            var song = new SongDocument { Title = "policy fixture", Notes = [new(60,0,100)], Provenance = new() { Synthetic = true } };
            throws(() => ScorePlaybackPolicy.EnsureRealInputAllowed(song)); song.Provenance.Synthetic = false;
            throws(() => ScorePlaybackPolicy.EnsureRealInputAllowed(song, new() { Provenance = new() { Synthetic = true } }));
            ScorePlaybackPolicy.EnsureRealInputAllowed(song);
        });
        test("Cancelled queries do not materialize scores or mutate catalogue", () =>
        {
            var (store,_,catalog) = Fixture(); string hash=LibraryCatalog.HashFile(catalog); using var cancel=new CancellationTokenSource(); cancel.Cancel();
            throws(() => store.Query(new(),cancel.Token)); check(store.SongReads==0 && hash==LibraryCatalog.HashFile(catalog),"cancel side effect");
        });
    }
}
