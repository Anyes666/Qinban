using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using QinBan.Core;

static class LegacySearchUpgradeTests
{
    private const string MarkerKey = "search_semantics";
    private const string MarkerVersion = "0.4.2";
    private sealed record Fixture(LibraryStore Store, string Root, string Catalog, LibraryEntry Unknown,
        LibraryEntry Und, LibraryEntry Rich, LibraryEntry BuiltIn, string Playlist);

    public static void Run(string fixtures, Action<string, Action> test, Action<bool, string> check)
    {
        int cases = 0, assertions = 0, failures = 0;
        void Check(bool condition, string why) { assertions++; check(condition, why); }
        void Case(string name, Action action)
        {
            cases++;
            test("Legacy search upgrade: " + name, () =>
            {
                try { action(); } catch { failures++; throw; }
            });
        }
        Fixture Create()
        {
            string root = Path.Combine(fixtures, "legacy-search-" + Guid.NewGuid().ToString("N"));
            string songs = Path.Combine(root, "builtin-fixtures"); Directory.CreateDirectory(songs);
            SongDocument Sample(string title, ScoreProvenance provenance) => new()
            {
                Title = title, Author = "编谱作者甲", Category = "隔离练习", Bpm = 100,
                Notes = [new(60, 0, 100), new(64, 250, 100)], Provenance = provenance
            };
            string resource = Path.Combine(songs, "fixture.json");
            File.WriteAllText(resource, SongParser.ToJson(Sample("只读内置夹具", new() { Synthetic = true })));
            var builtin = LibraryStore.Create(SongParser.Read(resource), "fixture.json", LibraryCatalog.HashFile(resource), true);
            builtin.Id = builtin.CatalogId = "builtin:legacy-search-fixture";
            string catalog = Path.Combine(songs, LibraryCatalog.FileName);
            LibraryCatalog.Build(catalog, [builtin], songs);
            File.SetAttributes(catalog, File.GetAttributes(catalog) | FileAttributes.ReadOnly);
            var store = new LibraryStore(Path.Combine(root, "isolated-state"), songs);
            var unknown = store.AddSong(Sample("空语种夹具", new() { Synthetic = true, Artist = "旧独唱者" }));
            var und = store.AddSong(Sample("未定语种夹具", new() { Synthetic = true, LanguageTags = ["und"] }));
            string source = Path.Combine(root, "original-input.json");
            File.WriteAllText(source, SongParser.ToJson(Sample("合作演唱夹具", new()
            {
                Synthetic = true, Artist = "旧演者", Artists = ["晓岚", "海风"], LanguageTags = ["yue", "en-US", "qaa-ZZ"],
                Album = "春潮", VersionLabel = "舞台纪念", Aliases = ["合作别名"], Tags = ["回归标签"],
                WorkId = "fixture:work", EditionId = "fixture:edition"
            })));
            var rich = store.Import(source).Entry;
            var builtInEntry = store.Find(builtin.Id)!;
            unknown.Favorite = true; unknown.Options.Transpose = 2;
            rich.Favorite = rich.InQueue = true; rich.Options.Speed = 1.25;
            rich.LastPlayedAt = DateTimeOffset.UnixEpoch.AddDays(1);
            builtInEntry.Favorite = builtInEntry.InQueue = true;
            store.SaveMany([unknown, rich, builtInEntry]);
            var playlist = store.CreatePlaylist("保留歌单"); store.AddToPlaylist(playlist.Id, [rich, builtInEntry, unknown]);
            using var connection = Open(store.DatabasePath);
            Execute(connection, "INSERT INTO retired_legacy VALUES('fixture:retired','{\"preserve\":true}')");
            return new(store, root, catalog, unknown, und, rich, builtInEntry, playlist.Id);
        }
        void Legacyize(Fixture fixture, string? previousVersion = null)
        {
            using var connection = Open(fixture.Store.DatabasePath); using var tx = connection.BeginTransaction();
            foreach (var entry in new[] { fixture.Unknown, fixture.Und, fixture.Rich })
            {
                // Recreate pre-0.4.2 derived fields only; keep current, complete metadata_json untouched.
                var fields = new[] { entry.Title, entry.Author, entry.Provenance.Artist, entry.Category, entry.Provenance.Provider }
                    .Concat(entry.Provenance.Aliases).Concat(entry.Provenance.Tags).Where(s => !string.IsNullOrWhiteSpace(s));
                var old = fields.Select(s => LibrarySearch.Build(new LibraryEntry { Title = s })).ToArray();
                using var command = connection.CreateCommand(); command.Transaction = tx;
                command.CommandText = "UPDATE search_index SET author_key=$author,search_text=$text,pinyin=$pinyin,initials=$initials WHERE entry_id=$id";
                command.Parameters.AddWithValue("$id", entry.CatalogId);
                command.Parameters.AddWithValue("$author", LibrarySearch.Normalize(entry.Author + " " + entry.Provenance.Artist));
                command.Parameters.AddWithValue("$text", string.Join(" | ", old.Select(k => k.Title)));
                command.Parameters.AddWithValue("$pinyin", string.Join(" | ", old.Select(k => k.SortTitle)));
                command.Parameters.AddWithValue("$initials", string.Join(" | ", old.Select(k => k.Initials.Split(" | ")[0])));
                command.ExecuteNonQuery();
            }
            using var marker = connection.CreateCommand(); marker.Transaction = tx;
            marker.CommandText = "DELETE FROM meta WHERE key=$key"; marker.Parameters.AddWithValue("$key", MarkerKey); marker.ExecuteNonQuery();
            if (previousVersion != null)
            {
                marker.CommandText = "INSERT INTO meta VALUES($key,$version)";
                marker.Parameters.AddWithValue("$version", previousVersion); marker.ExecuteNonQuery();
            }
            tx.Commit();
        }
        Dictionary<string, string> Snapshot(Fixture fixture) => new()
        {
            ["entries / exact metadata"] = Rows(fixture.Store.DatabasePath, "SELECT * FROM entries ORDER BY id"),
            ["user_state"] = Rows(fixture.Store.DatabasePath, "SELECT * FROM user_state ORDER BY catalog_id"),
            ["playlists"] = Rows(fixture.Store.DatabasePath, "SELECT * FROM playlists ORDER BY id"),
            ["playlist_items / order"] = Rows(fixture.Store.DatabasePath, "SELECT * FROM playlist_items ORDER BY playlist_id,position,catalog_id"),
            ["retired_legacy"] = Rows(fixture.Store.DatabasePath, "SELECT * FROM retired_legacy ORDER BY id"),
            ["other meta / schema version"] = Rows(fixture.Store.DatabasePath, $"SELECT * FROM meta WHERE key<>'{MarkerKey}' ORDER BY key"),
            ["schema"] = Rows(fixture.Store.DatabasePath, "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"),
            ["non-derived search columns"] = Rows(fixture.Store.DatabasePath, "SELECT entry_id,duration,added_ms,provider,timing_verified,completeness,human_reviewed FROM search_index ORDER BY entry_id"),
            ["builtin database hash"] = LibraryCatalog.HashFile(fixture.Catalog),
            ["original / normalized / builtin score hashes"] = JsonSerializer.Serialize(Directory.GetFiles(fixture.Root, "*.json", SearchOption.AllDirectories)
                .Order(StringComparer.Ordinal).Select(p => new { path = p, hash = LibraryCatalog.HashFile(p) }))
        };
        void Preserved(Fixture fixture, Dictionary<string, string> before)
        {
            var after = Snapshot(fixture);
            foreach (var pair in before) Check(after[pair.Key] == pair.Value, "changed " + pair.Key);
            Check((File.GetAttributes(fixture.Catalog) & FileAttributes.ReadOnly) != 0, "builtin no longer readonly");
        }
        void CurrentKeys(Fixture fixture)
        {
            foreach (var entry in new[] { fixture.Unknown, fixture.Und, fixture.Rich })
            {
                var expected = LibrarySearch.Build(entry);
                string actual = Rows(fixture.Store.DatabasePath,
                    $"SELECT title_key,author_key,search_text,pinyin,initials,sort_title FROM search_index WHERE entry_id='{entry.CatalogId}'");
                Check(actual == JsonSerializer.Serialize(new[] { new[] { expected.Title, expected.Author, expected.Text, expected.Pinyin, expected.Initials, expected.SortTitle } }),
                    "derived keys not current: " + entry.Id);
            }
        }
        void Searches(LibraryStore store, Fixture fixture)
        {
            var unknown = store.Query(new(Search: "语种未知", Filter: LibraryFilter.Personal));
            Check(unknown.Total == 2 && unknown.Items.Select(e => e.Id).ToHashSet().SetEquals([fixture.Unknown.Id, fixture.Und.Id]), "empty / und unknown language not searchable");
            foreach (string term in new[] { "晓岚", "海风", "xiaolan", "hf", "春潮", "chunchao", "cc", "舞台纪念", "wutaijinian", "wtjn",
                "粤语", "英语", "en-US", "qaa-ZZ", "晓岚 英语 春潮 舞台纪念", "合作别名", "回归标签" })
            {
                var page = store.Query(new(Search: term, Filter: LibraryFilter.Personal));
                Check(page.Total == 1 && page.Items.Single().Id == fixture.Rich.Id, "new metadata search missing: " + term);
            }
            Check(store.Query(new(Search: "编谱作者甲", Filter: LibraryFilter.Personal)).Total == 3, "author search lost");
            Check(store.Query(new(Search: "旧演者", Filter: LibraryFilter.Personal)).Total == 1, "legacy Artist search lost");
        }
        Case("old schema=1 upgrades unknown language and actual new fields without touching source data", () =>
        {
            var fixture = Create(); Legacyize(fixture);
            Check(fixture.Store.Query(new(Search: "语种未知", Filter: LibraryFilter.Personal)).Total == 0, "fixture is not old unknown-language index");
            Check(fixture.Store.Query(new(Search: "晓岚", Filter: LibraryFilter.Personal)).Total == 0, "fixture is not old artist index");
            var before = Snapshot(fixture); LibraryStore reopened;
            using (LockScores(fixture))
            {
                reopened = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory);
                Check(reopened.SongReads == 0, "upgrade read scores"); Searches(reopened, fixture);
                Check(reopened.SongReads == 0 && reopened.LoadWarnings.Count == 0, "search read scores / silently skipped upgrade");
            }
            CurrentKeys(fixture); Preserved(fixture, before);
            Check(Marker(fixture) == MarkerVersion, "upgrade marker missing / wrong version");
            Check(reopened.Query(new(Favorites: true)).Total == 3 && reopened.Query(new(Queue: true)).Total == 2, "favorite / queue lost");
            Check(reopened.Query(new(PlaylistId: fixture.Playlist)).Items.Select(e => e.Id).SequenceEqual([fixture.Rich.Id, fixture.BuiltIn.Id, fixture.Unknown.Id]), "playlist order lost");
            var rich = reopened.Find(fixture.Rich.Id)!;
            Check(rich.Author == "编谱作者甲" && rich.Options.Speed == 1.25 && rich.LastPlayedAt == DateTimeOffset.UnixEpoch.AddDays(1), "author / options / recent state changed");
        });
        Case("new empty database marks current semantics and imports remain current", () =>
        {
            var fixture = Create(); string data = Path.Combine(fixture.Root, "brand-new-state");
            var store = new LibraryStore(data, fixture.Store.BuiltInDirectory);
            Check(Rows(store.DatabasePath, $"SELECT value FROM meta WHERE key='{MarkerKey}'") == JsonSerializer.Serialize(new[] { new[] { MarkerVersion } }), "new DB marker missing");
            Check(store.Query(new(Filter: LibraryFilter.Personal)).Total == 0 && store.SongReads == 0, "new DB has personal entries / eager score reads");
            var entry = store.AddSong(new() { Title = "新库夹具", Author = "新作者", Notes = [new(60, 0, 100)], Provenance = new() { Synthetic = true, Artists = ["新歌手"], Album = "新专辑" } });
            string before = LibraryCatalog.HashFile(store.DatabasePath);
            var reopened = new LibraryStore(data, fixture.Store.BuiltInDirectory);
            foreach (string term in new[] { "语种未知", "新歌手", "新专辑" })
                Check(reopened.Query(new(Search: term, Filter: LibraryFilter.Personal)).Items.Single().Id == entry.Id, "new DB search missing: " + term);
            Check(before == LibraryCatalog.HashFile(store.DatabasePath) && reopened.SongReads == 0, "new DB reopened with writes / reads");
        });
        Case("committed marker makes repeated opens zero-write and zero-score-read", () =>
        {
            var fixture = Create(); Legacyize(fixture);
            _ = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory);
            Check(Marker(fixture) == MarkerVersion, "cannot test idempotence without committed marker");
            using (var connection = Open(fixture.Store.DatabasePath))
                foreach (string table in new[] { "search_index", "meta" })
                    foreach (string action in new[] { "INSERT", "UPDATE", "DELETE" })
                        Execute(connection, $"CREATE TRIGGER no_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'unexpected reopen write'); END;");
            var before = Snapshot(fixture); string databaseHash = LibraryCatalog.HashFile(fixture.Store.DatabasePath);
            using (LockScores(fixture))
                for (int i = 0; i < 2; i++)
                {
                    var reopened = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory);
                    Check(reopened.SongReads == 0, "reopen read scores"); Searches(reopened, fixture);
                }
            Check(databaseHash == LibraryCatalog.HashFile(fixture.Store.DatabasePath), "reopen rewrote database"); Preserved(fixture, before);
        });
        var corruptions = new (string Name, Func<string, string> Change)[]
        {
            ("malformed JSON", _ => "{bad-json"),
            ("JSON null", _ => "null"),
            ("null provenance", json => Changed(json, node => node["provenance"] = null)),
            ("null author", json => Changed(json, node => node["author"] = null)),
            ("duplicate artists", json => Changed(json, node => node["provenance"]!["artists"] = new JsonArray("晓岚", "晓岚"))),
            ("invalid language tag", json => Changed(json, node => node["provenance"]!["languageTags"] = new JsonArray("not_a_tag"))),
            ("escaping resource path", json => Changed(json, node => node["relativePath"] = "../outside.json")),
            ("null options", json => Changed(json, node => node["options"] = null)),
            ("invalid playback options", json => Changed(json, node => node["options"]!["speed"] = -1)),
            ("inconsistent catalogue ID", json => Changed(json, node => node["catalogId"] = "wrong:id"))
        };
        foreach (var corruption in corruptions)
            Case("preflight rejects " + corruption.Name + " before any derived writes", () =>
            {
                var fixture = Create(); Legacyize(fixture);
                string badId;
                using (var connection = Open(fixture.Store.DatabasePath))
                {
                    badId = Scalar(connection, "SELECT id FROM entries ORDER BY id DESC LIMIT 1")!;
                    using var update = connection.CreateCommand(); update.CommandText = "UPDATE entries SET metadata_json=$json WHERE id=$id";
                    update.Parameters.AddWithValue("$id", badId);
                    update.Parameters.AddWithValue("$json", corruption.Change(Scalar(connection, "SELECT metadata_json FROM entries WHERE id='" + badId + "'")!));
                    update.ExecuteNonQuery();
                    Execute(connection, "CREATE TRIGGER require_preflight BEFORE UPDATE ON search_index BEGIN SELECT RAISE(ABORT,'write before all metadata validated'); END;");
                }
                var before = Snapshot(fixture); string hash = LibraryCatalog.HashFile(fixture.Store.DatabasePath);
                var keys = Rows(fixture.Store.DatabasePath, "SELECT * FROM search_index ORDER BY entry_id");
                Exception? error = OpenFailure(fixture);
                Check(error is FormatException, "bad metadata not explicitly rejected: " + (error?.Message ?? "no exception"));
                Check(error!.Message.Contains(badId, StringComparison.Ordinal), "preflight failure omitted damaged entry ID");
                Check(Marker(fixture) == null && hash == LibraryCatalog.HashFile(fixture.Store.DatabasePath), "failed preflight marked or modified DB");
                Check(keys == Rows(fixture.Store.DatabasePath, "SELECT * FROM search_index ORDER BY entry_id"), "failed preflight changed keys");
                Preserved(fixture, before);
            });
        Case("missing search row rejects upgrade instead of committing a partial marker", () =>
        {
            var fixture = Create(); Legacyize(fixture);
            using (var connection = Open(fixture.Store.DatabasePath)) Execute(connection, $"DELETE FROM search_index WHERE entry_id='{fixture.Rich.Id}'");
            var before = Snapshot(fixture); string hash = LibraryCatalog.HashFile(fixture.Store.DatabasePath);
            Check(OpenFailure(fixture) is FormatException, "missing index row accepted");
            Check(Marker(fixture) == null && hash == LibraryCatalog.HashFile(fixture.Store.DatabasePath), "missing index row was repaired / partially committed");
            Preserved(fixture, before);
        });
        foreach (bool markerFailure in new[] { false, true })
            Case(markerFailure ? "marker write failure rolls back every derived update" : "mid-rebuild write failure rolls back every derived update", () =>
            {
                var fixture = Create(); Legacyize(fixture);
                using (var connection = Open(fixture.Store.DatabasePath))
                {
                    string when = markerFailure ? $"INSERT ON meta WHEN NEW.key='{MarkerKey}'"
                        : "UPDATE ON search_index WHEN NEW.entry_id=(SELECT max(id) FROM entries)";
                    Execute(connection, $"CREATE TRIGGER fail_upgrade BEFORE {when} BEGIN SELECT RAISE(ABORT,'injected upgrade failure'); END;");
                }
                var before = Snapshot(fixture); string hash = LibraryCatalog.HashFile(fixture.Store.DatabasePath);
                string keys = Rows(fixture.Store.DatabasePath, "SELECT * FROM search_index ORDER BY entry_id");
                var error = OpenFailure(fixture);
                Check(error is SqliteException && error.Message.Contains("injected upgrade failure"), "transaction fault not exercised");
                Check(hash == LibraryCatalog.HashFile(fixture.Store.DatabasePath), "rolled-back DB bytes changed");
                Check(Marker(fixture) == null && keys == Rows(fixture.Store.DatabasePath, "SELECT * FROM search_index ORDER BY entry_id"), "partial keys / marker survived rollback");
                Preserved(fixture, before);
                using (var connection = Open(fixture.Store.DatabasePath)) Execute(connection, "DROP TRIGGER fail_upgrade");
                var reopened = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory);
                Check(Marker(fixture) == MarkerVersion && reopened.SongReads == 0, "retry after rollback did not commit");
                Searches(reopened, fixture); CurrentKeys(fixture);
            });
        Case("older semantic marker upgrades once without schema bump", () =>
        {
            var fixture = Create(); Legacyize(fixture, "0.4.1"); var before = Snapshot(fixture);
            var reopened = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory);
            Check(Marker(fixture) == MarkerVersion, "older semantic version did not upgrade");
            Searches(reopened, fixture); CurrentKeys(fixture); Preserved(fixture, before);
            Check(reopened.SongReads == 0, "versioned upgrade read scores");
        });
        Console.WriteLine($"LEGACY SEARCH RESULT: {cases - failures}/{cases} cases passed; {assertions} assertions; {failures} failures");
    }

    private static SqliteConnection Open(string path)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
        connection.Open(); return connection;
    }
    private static void Execute(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand(); command.CommandText = sql; command.ExecuteNonQuery();
    }
    private static string? Scalar(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand(); command.CommandText = sql; return command.ExecuteScalar() as string;
    }
    private static string? Marker(Fixture fixture)
    {
        using var connection = Open(fixture.Store.DatabasePath); return Scalar(connection, $"SELECT value FROM meta WHERE key='{MarkerKey}'");
    }
    private static string Rows(string path, string sql)
    {
        using var connection = Open(path); using var command = connection.CreateCommand(); command.CommandText = sql;
        using var reader = command.ExecuteReader(); var rows = new List<object[]>();
        while (reader.Read()) { var row = new object[reader.FieldCount]; reader.GetValues(row); rows.Add(row); }
        return JsonSerializer.Serialize(rows);
    }
    private static string Changed(string json, Action<JsonNode> change)
    {
        var node = JsonNode.Parse(json)!; change(node); return node.ToJsonString(JsonDefaults.Options);
    }
    private static Exception? OpenFailure(Fixture fixture)
    {
        try { using var scores = LockScores(fixture); _ = new LibraryStore(fixture.Store.DataDirectory, fixture.Store.BuiltInDirectory); return null; }
        catch (Exception ex) { return ex; }
    }
    private sealed class ScoreLocks : IDisposable
    {
        private readonly List<FileStream> streams = [];
        public ScoreLocks(string root)
        {
            try { foreach (string path in Directory.GetFiles(root, "*.json", SearchOption.AllDirectories)) streams.Add(new(path, FileMode.Open, FileAccess.Read, FileShare.None)); }
            catch { Dispose(); throw; }
        }
        public void Dispose() { foreach (var stream in streams) stream.Dispose(); }
    }
    private static ScoreLocks LockScores(Fixture fixture) => new(fixture.Root);
}
