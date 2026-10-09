using System.Collections;
using System.Text.Json;
using Microsoft.Data.Sqlite;
namespace QinBan.Core;

public sealed class LibraryStore
{
    private readonly object _gate = new();
    private readonly Dictionary<string, (LibraryEntry Entry, string State)> _observed = [];
    private readonly Queue<string> _cacheOrder = new();
    private readonly string _catalogPath;
    public string DataDirectory { get; }
    public string BuiltInDirectory { get; }
    public string DatabasePath => Path.Combine(DataDirectory, "library.db");
    public IReadOnlyList<LibraryEntry> Entries { get; }
    public List<string> LoadWarnings { get; } = [];
    public bool MigratedLegacy { get; private set; }
    public int SongReads => Volatile.Read(ref _songReads);
    public int Count { get { lock (_gate) { using var c = Connect(); return CountAll(c); } } }
    private sealed record EntryState(bool Favorite, bool InQueue, DateTimeOffset? LastPlayedAt, PlayOptions Options);
    private static string StateJson(LibraryEntry e) => JsonSerializer.Serialize(new EntryState(e.Favorite, e.InQueue, e.LastPlayedAt, e.Options), JsonDefaults.Options);

    public LibraryStore(string dataDirectory, string builtInDirectory)
    {
        DataDirectory = Path.GetFullPath(dataDirectory); BuiltInDirectory = Path.GetFullPath(builtInDirectory);
        Directory.CreateDirectory(DataDirectory); Directory.CreateDirectory(Path.Combine(DataDirectory, "scores")); Directory.CreateDirectory(Path.Combine(DataDirectory, "originals"));
        string supplied = Path.Combine(BuiltInDirectory, LibraryCatalog.FileName);
        _catalogPath = File.Exists(supplied) ? supplied : BuildFallback();
        using (var catalog = LibraryCatalog.Open(_catalogPath, SqliteOpenMode.ReadOnly))
        {
            using var check = catalog.CreateCommand(); check.CommandText = "SELECT value FROM meta WHERE key='schema'";
            if (Convert.ToString(check.ExecuteScalar()) != LibraryCatalog.SchemaVersion.ToString()) throw new FormatException("内置目录格式不支持；没有修改原文件。");
        }
        InitializeUserDatabase();
        Entries = new EntryView(this);
    }
    private string BuildFallback()
    {
        // Compatibility for pre-indexed releases and tests only. Release 0.4 ships a read-only catalogue.
        var entries = new List<LibraryEntry>();
        if (Directory.Exists(BuiltInDirectory))
        {
            foreach (string path in Directory.GetFiles(BuiltInDirectory, "*.json").Order(StringComparer.Ordinal))
            {
                try
                {
                    var song = SongParser.Read(path); string relative = Path.GetFileName(path);
                    var entry = Create(song, relative, LibraryCatalog.HashFile(path), true);
                    entry.Id = entry.CatalogId = "builtin:" + relative;
                    entry.AddedAt = DateTimeOffset.UnixEpoch.AddMilliseconds(entries.Count);
                    entries.Add(entry);
                }
                catch (Exception ex) { LoadWarnings.Add($"内置谱 {Path.GetFileName(path)}：{ex.Message}"); }
            }
        }
        string pathOut = Path.Combine(DataDirectory, ".catalog", LibraryCatalog.FileName);
        LibraryCatalog.Build(pathOut, entries, BuiltInDirectory); return pathOut;
    }
    private void InitializeUserDatabase()
    {
        string legacyPath = Path.Combine(DataDirectory, "library.json");
        bool exists = File.Exists(DatabasePath);
        using var connection = LibraryCatalog.Open(DatabasePath, SqliteOpenMode.ReadWriteCreate);
        if (!exists)
        {
            using var transaction = connection.BeginTransaction();
            LibraryCatalog.Execute(connection, LibraryCatalog.Schema + """
                CREATE TABLE user_state(catalog_id TEXT PRIMARY KEY, legacy_id TEXT UNIQUE, favorite INTEGER NOT NULL,
                    in_queue INTEGER NOT NULL, last_played_ms INTEGER, state_json TEXT NOT NULL);
                CREATE TABLE retired_legacy(id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
                CREATE TABLE playlists(id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, created_ms INTEGER NOT NULL);
                CREATE TABLE playlist_items(playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    catalog_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY(playlist_id,catalog_id));
                CREATE INDEX playlist_order ON playlist_items(playlist_id,position,catalog_id);
                INSERT INTO meta(key,value) VALUES('schema','1');
                """, transaction);
            transaction.Commit();
        }
        using (var check = connection.CreateCommand())
        {
            check.CommandText = "PRAGMA quick_check";
            if (Convert.ToString(check.ExecuteScalar()) != "ok") throw new FormatException("用户数据库校验失败；文件已保留，请先备份。 ");
            check.CommandText = "SELECT value FROM meta WHERE key='schema'";
            if (Convert.ToString(check.ExecuteScalar()) != "1") throw new FormatException("用户数据库版本不支持；没有清空或替换数据。");
            UpgradeUserSearchIndex(connection);
            check.CommandText = "SELECT value FROM meta WHERE key='legacy_migrated'";
            if (check.ExecuteScalar() != null) return;
        }
        var legacy = new List<LibraryEntry>();
        if (File.Exists(legacyPath))
        {
            if (new FileInfo(legacyPath).Length > 128L * 1024 * 1024) throw new FormatException("旧索引过大，请保留文件并检查。");
            legacy = JsonSerializer.Deserialize<List<LibraryEntry>>(File.ReadAllText(legacyPath), JsonDefaults.Options) ?? throw new FormatException("旧曲库索引为空；原文件已保留。");
            if (legacy.Count > 100_000 || legacy.Select(e => e.Id).Distinct().Count() != legacy.Count) throw new FormatException("旧曲库条目超限或 ID 重复；原文件已保留。");
            foreach (var entry in legacy) { LibraryCatalog.ValidateEntry(entry); _ = ResolvePath(entry); }
            // A copy, never a move/overwrite. The original remains readable by the old application.
            string backup = legacyPath + ".pre-sqlite-" + DateTimeOffset.UtcNow.ToString("yyyyMMddTHHmmss") + "-" + Guid.NewGuid().ToString("N")[..8] + ".bak";
            File.Copy(legacyPath, backup, false);
        }
        using var catalog = LibraryCatalog.Open(_catalogPath, SqliteOpenMode.ReadOnly);
        using var migrate = connection.BeginTransaction();
        foreach (var entry in legacy)
        {
            if (entry.BuiltIn)
            {
                using var find = catalog.CreateCommand(); find.CommandText = "SELECT id FROM entries WHERE relative_path=$path ORDER BY id LIMIT 1"; find.Parameters.AddWithValue("$path", entry.RelativePath);
                if (find.ExecuteScalar() is string id)
                {
                    entry.CatalogId = id; WriteState(connection, migrate, entry);
                }
                else
                {
                    using var retired = connection.CreateCommand(); retired.Transaction = migrate;
                    retired.CommandText = "INSERT INTO retired_legacy VALUES($id,$json)";
                    retired.Parameters.AddWithValue("$id", entry.Id); retired.Parameters.AddWithValue("$json", JsonSerializer.Serialize(entry, JsonDefaults.Options)); retired.ExecuteNonQuery();
                    LoadWarnings.Add("旧内置条目未在新目录找到，状态已保留：" + entry.Title);
                }
            }
            else
            {
                entry.CatalogId = entry.Id;
                string resource = ResolvePath(entry);
                if (File.Exists(resource)) entry.ResourceHash = LibraryCatalog.HashFile(resource);
                else LoadWarnings.Add("旧个人谱文件缺失，条目/设置仍保留：" + entry.Title);
                LibraryCatalog.Insert(connection, migrate, entry); WriteState(connection, migrate, entry);
            }
        }
        using (var marker = connection.CreateCommand())
        {
            marker.Transaction = migrate; marker.CommandText = "INSERT INTO meta VALUES('legacy_migrated',$status)";
            marker.Parameters.AddWithValue("$status", File.Exists(legacyPath) ? "copied" : "not-present"); marker.ExecuteNonQuery();
        }
        migrate.Commit(); MigratedLegacy = legacy.Count > 0;
        if (MigratedLegacy) LoadWarnings.Insert(0, $"已复制迁移 {legacy.Count} 个旧条目；旧 JSON 与原谱未覆盖。");
    }
    private const string SearchSemanticsVersion = "0.4.2";
    private static SearchKeys UpgradeSearchKeys(string id, string json)
    {
        try
        {
            var entry = JsonSerializer.Deserialize<LibraryEntry>(json, JsonDefaults.Options);
            if (entry == null || entry.Author == null || entry.Category == null || entry.CatalogId == null
                || entry.Options == null || entry.Provenance == null) throw new FormatException("曲库条目含空元数据。");
            LibraryCatalog.ValidateEntry(entry);
            if ((entry.CatalogId.Length > 0 ? entry.CatalogId : entry.Id) != id) throw new FormatException("曲库条目 ID 不一致。");
            return LibrarySearch.Build(entry);
        }
        catch (Exception ex) when (ex is JsonException or FormatException or ArgumentException)
        {
            throw new FormatException($"个人曲库检索升级失败（条目 {id}）：元数据无效；数据库已保留。", ex);
        }
    }
    private static void UpgradeUserSearchIndex(SqliteConnection connection)
    {
        using var transaction = connection.BeginTransaction();
        using (var marker = connection.CreateCommand())
        {
            marker.Transaction = transaction; marker.CommandText = "SELECT value FROM meta WHERE key='search_semantics'";
            if (Convert.ToString(marker.ExecuteScalar()) == SearchSemanticsVersion) return;
        }
        // Two streaming passes: validate every pending entry before writes, without retaining all JSON/entries.
        // Only the personal database is involved; no score files or read-only catalogue rows are read/rebuilt.
        using var read = connection.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT e.id,e.metadata_json,k.entry_id FROM entries e LEFT JOIN search_index k ON k.entry_id=e.id ORDER BY e.id";
        using (var reader = read.ExecuteReader())
            while (reader.Read())
            {
                string id = reader.GetString(0);
                _ = UpgradeSearchKeys(id, reader.GetString(1));
                if (reader.IsDBNull(2)) throw new FormatException($"个人曲库检索升级失败（条目 {id}）：缺少检索索引；数据库已保留。");
            }
        using var update = connection.CreateCommand(); update.Transaction = transaction;
        update.CommandText = "UPDATE search_index SET title_key=$title,author_key=$author,search_text=$text,pinyin=$pinyin,initials=$initials,sort_title=$sort WHERE entry_id=$id";
        foreach (string name in new[] { "$id", "$title", "$author", "$text", "$pinyin", "$initials", "$sort" }) update.Parameters.Add(name, SqliteType.Text);
        read.CommandText = "SELECT id,metadata_json FROM entries ORDER BY id";
        using (var reader = read.ExecuteReader())
            while (reader.Read())
            {
                string id = reader.GetString(0); var keys = UpgradeSearchKeys(id, reader.GetString(1));
                update.Parameters["$id"].Value = id; update.Parameters["$title"].Value = keys.Title;
                update.Parameters["$author"].Value = keys.Author; update.Parameters["$text"].Value = keys.Text;
                update.Parameters["$pinyin"].Value = keys.Pinyin; update.Parameters["$initials"].Value = keys.Initials;
                update.Parameters["$sort"].Value = keys.SortTitle;
                if (update.ExecuteNonQuery() != 1) throw new FormatException($"个人曲库检索升级失败（条目 {id}）：索引更新数量异常；数据库已保留。");
            }
        using (var marker = connection.CreateCommand())
        {
            marker.Transaction = transaction;
            marker.CommandText = "INSERT INTO meta(key,value) VALUES('search_semantics',$version) ON CONFLICT(key) DO UPDATE SET value=excluded.value";
            marker.Parameters.AddWithValue("$version", SearchSemanticsVersion); marker.ExecuteNonQuery();
        }
        transaction.Commit();
    }
    private SqliteConnection Connect()
    {
        // A URI main filename enables URI handling for ATTACH as well; the catalogue remains mode=ro.
        var connection = LibraryCatalog.Open(new Uri(DatabasePath).AbsoluteUri + "?mode=rw", SqliteOpenMode.ReadWrite);
        using var attach = connection.CreateCommand(); attach.CommandText = "ATTACH DATABASE $path AS builtin";
        attach.Parameters.AddWithValue("$path", new Uri(_catalogPath).AbsoluteUri + "?mode=ro"); attach.ExecuteNonQuery(); return connection;
    }
    // Search/count/order remain SQL-side; only page IDs are materialized by the app, then payload JSON is read for those IDs.
    private const string BaseSql = """
        WITH base AS (
            SELECT k.entry_id AS catalog_id,k.*,e.metadata_json AS metadata_json,1 AS builtin,
                COALESCE(s.favorite,0) AS favorite,COALESCE(s.in_queue,0) AS in_queue,s.last_played_ms
            FROM builtin.search_index k
                JOIN builtin.entries e ON e.id=k.entry_id
                LEFT JOIN main.user_state s ON s.catalog_id=k.entry_id
            UNION ALL
            SELECT k.entry_id,k.*,e.metadata_json,0,COALESCE(s.favorite,0),COALESCE(s.in_queue,0),s.last_played_ms
            FROM main.search_index k
                JOIN main.entries e ON e.id=k.entry_id
                LEFT JOIN main.user_state s ON s.catalog_id=k.entry_id
        )
        """;
    private const string PayloadSql = """
        SELECT e.id,COALESCE(s.legacy_id,e.id),e.metadata_json,1,s.state_json
        FROM builtin.entries e LEFT JOIN main.user_state s ON s.catalog_id=e.id
        WHERE e.id=$id OR e.id=(SELECT catalog_id FROM main.user_state WHERE legacy_id=$id)
        UNION ALL
        SELECT e.id,COALESCE(s.legacy_id,e.id),e.metadata_json,0,s.state_json
        FROM main.entries e LEFT JOIN main.user_state s ON s.catalog_id=e.id
        WHERE e.id=$id OR e.id=(SELECT catalog_id FROM main.user_state WHERE legacy_id=$id)
        LIMIT 1
        """;
    private LibraryEntry? ReadEntry(SqliteCommand command, string id)
    {
        command.Parameters["$id"].Value = id;
        using var reader = command.ExecuteReader(); if (!reader.Read()) return null;
        var entry = JsonSerializer.Deserialize<LibraryEntry>(reader.GetString(2), JsonDefaults.Options)
            ?? throw new FormatException("曲库条目损坏，已保留数据库。");
        entry.CatalogId = reader.GetString(0); entry.Id = reader.GetString(1); entry.BuiltIn = reader.GetInt32(3) == 1;
        if (!reader.IsDBNull(4)) ApplyState(entry, reader.GetString(4)); return Observe(entry);
    }
    private static int CountAll(SqliteConnection connection)
    {
        using var c = connection.CreateCommand(); c.CommandText = "SELECT (SELECT count(*) FROM builtin.entries)+(SELECT count(*) FROM main.entries)";
        return Convert.ToInt32(c.ExecuteScalar());
    }
    // These predicates read explicit provenance metadata rather than title/search text.
    // A declared zh/cmn/yue language is sufficient for the Chinese-pop lane; an
    // editorial Chinese/Cantonese tag remains supported for legacy records.
    private const string ChineseOrCantoneseTagPredicate = """
        (
            EXISTS (
                SELECT 1 FROM json_each(metadata_json, '$.provenance.tags') AS tag
                WHERE tag.value IN ('中文歌曲','中文流行','中文流行候选','粤语歌曲','粤语流行','粤语流行候选')
            )
            OR EXISTS (
                SELECT 1 FROM json_each(metadata_json, '$.provenance.languageTags') AS language_tag
                WHERE lower(CAST(language_tag.value AS TEXT)) IN ('zh','cmn','yue')
                   OR lower(CAST(language_tag.value AS TEXT)) LIKE 'zh-%'
                   OR lower(CAST(language_tag.value AS TEXT)) LIKE 'cmn-%'
                   OR lower(CAST(language_tag.value AS TEXT)) LIKE 'yue-%'
            )
        )
        """;
    private const string PopularPriorityTagPredicate = """
        EXISTS (
            SELECT 1 FROM json_each(metadata_json, '$.provenance.tags') AS tag
            WHERE tag.value = '大众优先'
        )
        """;

    private const string UnknownLanguagePredicate = """
        (
            NOT EXISTS (
                SELECT 1 FROM json_each(metadata_json, '$.provenance.languageTags') AS language_tag
            )
            OR EXISTS (
                SELECT 1 FROM json_each(metadata_json, '$.provenance.languageTags') AS language_tag
                WHERE lower(CAST(language_tag.value AS TEXT)) IN ('und','unknown','unspecified')
            )
        )
        """;

    private static (string Where, string Order) Conditions(SqliteCommand command, LibraryQuery query)
    {
        if (query.Offset < 0 || query.Limit is < 1 or > 1000) throw new FormatException("分页范围无效（每页 1–1000 项）。");
        string[] terms = LibrarySearch.Terms(query.Search); var clauses = new List<string>();
        for (int i = 0; i < terms.Length; i++)
        {
            string name = "$term" + i; command.Parameters.AddWithValue(name, terms[i]);
            clauses.Add($"(instr(search_text,{name})>0 OR instr(pinyin,{name})>0 OR instr(initials,{name})>0)");
        }
        if (terms.Length == 0 && !string.IsNullOrWhiteSpace(query.Search)) clauses.Add("0");
        switch (query.Filter)
        {
            case LibraryFilter.Personal: clauses.Add("builtin=0"); break;
            case LibraryFilter.BuiltIn: clauses.Add("builtin=1"); break;
            case LibraryFilter.Recent: clauses.Add("last_played_ms IS NOT NULL"); break;
            case LibraryFilter.Samples: clauses.Add("provider='mutopia'"); break;
            case LibraryFilter.ChinesePop: clauses.Add(ChineseOrCantoneseTagPredicate); break;
            case LibraryFilter.ChinesePopular:
                clauses.Add($"{PopularPriorityTagPredicate} AND {ChineseOrCantoneseTagPredicate}"); break;
            case LibraryFilter.UnknownLanguage: clauses.Add(UnknownLanguagePredicate); break;
        }
        if (query.Favorites) clauses.Add("favorite=1"); if (query.Queue) clauses.Add("in_queue=1");
        if (query.PlaylistId != null) { clauses.Add("catalog_id IN (SELECT catalog_id FROM main.playlist_items WHERE playlist_id=$playlist)"); command.Parameters.AddWithValue("$playlist", query.PlaylistId); }
        if (query.WorkId != null) { clauses.Add("((builtin=1 AND catalog_id IN (SELECT id FROM builtin.entries WHERE work_id=$work)) OR (builtin=0 AND catalog_id IN (SELECT id FROM main.entries WHERE work_id=$work)))"); command.Parameters.AddWithValue("$work", query.WorkId); }
        switch (query.Quality)
        {
            case LibraryQuality.TimingCompared: clauses.Add("timing_verified=1"); break;
            case LibraryQuality.NotHumanReviewed: clauses.Add("human_reviewed=0"); break;
            case LibraryQuality.Exercises: clauses.Add("completeness='exercise'"); break;
        }
        string order = query.Sort switch
        {
            LibrarySort.Title => "sort_title ASC,catalog_id ASC",
            LibrarySort.Duration => "duration ASC,catalog_id ASC",
            LibrarySort.Recent => "last_played_ms DESC,catalog_id ASC",
            LibrarySort.ChinesePopular => $"CASE WHEN {PopularPriorityTagPredicate} AND {ChineseOrCantoneseTagPredicate} THEN 0 WHEN {ChineseOrCantoneseTagPredicate} THEN 1 ELSE 2 END,added_ms ASC,catalog_id ASC",
            _ => "added_ms ASC,catalog_id ASC"
        };
        if (query.PlaylistId != null && query.Sort == LibrarySort.Added) order = "(SELECT position FROM main.playlist_items pi WHERE pi.playlist_id=$playlist AND pi.catalog_id=base.catalog_id),catalog_id";
        if (terms.Length > 0)
        {
            command.Parameters.AddWithValue("$exact", LibrarySearch.Normalize(query.Search));
            order = "CASE WHEN title_key=$exact THEN 0 WHEN substr(title_key,1,length($exact))=$exact THEN 1 ELSE 2 END," + order;
        }
        return (clauses.Count == 0 ? "1" : string.Join(" AND ", clauses), order);
    }
    public LibraryPage Query(LibraryQuery query, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            cancellationToken.ThrowIfCancellationRequested(); using var connection = Connect(); using var command = connection.CreateCommand();
            var (where, order) = Conditions(command, query);
            command.CommandText = BaseSql + " SELECT count(*) FROM base WHERE " + where;
            int total = Convert.ToInt32(command.ExecuteScalar()); int all = CountAll(connection);
            command.CommandText = BaseSql + $" SELECT catalog_id FROM base WHERE {where} ORDER BY {order} LIMIT $limit OFFSET $offset";
            command.Parameters.AddWithValue("$limit", query.Limit); command.Parameters.AddWithValue("$offset", query.Offset);
            var ids = new List<string>();
            using (var reader = command.ExecuteReader())
                while (reader.Read()) { cancellationToken.ThrowIfCancellationRequested(); ids.Add(reader.GetString(0)); }
            using var payload = connection.CreateCommand(); payload.CommandText = PayloadSql; payload.Parameters.AddWithValue("$id", "");
            var rows = new List<LibraryEntry>();
            foreach (string id in ids)
            {
                cancellationToken.ThrowIfCancellationRequested();
                rows.Add(ReadEntry(payload, id) ?? throw new FormatException("目录与搜索索引不一致；数据库未清空。"));
            }
            return new(rows, total, all, query.Offset, query.Limit);
        }
    }
    private static void ApplyState(LibraryEntry entry, string json)
    {
        var state = JsonSerializer.Deserialize<EntryState>(json, JsonDefaults.Options) ?? throw new FormatException("用户状态损坏，已保留数据库。");
        state.Options.Validate(); entry.Favorite = state.Favorite; entry.InQueue = state.InQueue; entry.LastPlayedAt = state.LastPlayedAt; entry.Options = state.Options;
    }
    private LibraryEntry Observe(LibraryEntry entry)
    {
        if (_observed.TryGetValue(entry.CatalogId, out var old)) return old.Entry;
        while (_observed.Count >= 2048 && _cacheOrder.TryDequeue(out string? first)) _observed.Remove(first);
        _observed[entry.CatalogId] = (entry, StateJson(entry)); _cacheOrder.Enqueue(entry.CatalogId); return entry;
    }
    public IEnumerable<LibraryEntry> Enumerate(LibraryQuery query)
    {
        int offset = query.Offset;
        while (true)
        {
            var page = Query(query with { Offset = offset, Limit = 1000 });
            foreach (var entry in page.Items) yield return entry;
            offset += page.Items.Count; if (offset >= page.Total || page.Items.Count == 0) yield break;
        }
    }
    public LibraryEntry? Find(string id)
    {
        lock (_gate)
        {
            using var connection = Connect(); using var command = connection.CreateCommand();
            command.CommandText = PayloadSql; command.Parameters.AddWithValue("$id", id); return ReadEntry(command, id);
        }
    }
    public int FindPosition(LibraryQuery query, LibraryEntry entry)
    {
        lock (_gate)
        {
            using var connection = Connect(); using var command = connection.CreateCommand(); var (where, order) = Conditions(command, query);
            command.CommandText = BaseSql + $", positions AS (SELECT catalog_id,row_number() OVER (ORDER BY {order})-1 AS position FROM base WHERE {where}) SELECT position FROM positions WHERE catalog_id=$id";
            command.Parameters.AddWithValue("$id", entry.CatalogId.Length > 0 ? entry.CatalogId : entry.Id);
            object? value = command.ExecuteScalar(); return value == null ? -1 : Convert.ToInt32(value);
        }
    }
    public int FindOffset(LibraryQuery query, LibraryEntry entry)
    {
        int position = FindPosition(query, entry); return position < 0 ? -1 : position / query.Limit * query.Limit;
    }
    public LibraryStatistics Statistics()
    {
        lock (_gate)
        {
            using var c = Connect(); using var cmd = c.CreateCommand();
            cmd.CommandText = BaseSql + " SELECT count(*),(SELECT count(DISTINCT work_id) FROM (SELECT work_id FROM builtin.entries UNION ALL SELECT work_id FROM main.entries)),sum(provider='mutopia'),sum(builtin=0) FROM base";
            using var reader = cmd.ExecuteReader(); reader.Read();
            int scores = reader.GetInt32(0), works = reader.GetInt32(1), samples = reader.IsDBNull(2) ? 0 : reader.GetInt32(2), users = reader.IsDBNull(3) ? 0 : reader.GetInt32(3);
            reader.Close();
            // This release has no human-reviewed game arrangements: do not infer precision from parsing.
            cmd.CommandText = "SELECT e.metadata_json FROM builtin.entries e JOIN builtin.search_index k ON k.entry_id=e.id WHERE k.human_reviewed=1";
            int formal = 0; using var formalReader = cmd.ExecuteReader();
            while (formalReader.Read()) if (JsonSerializer.Deserialize<LibraryEntry>(formalReader.GetString(0), JsonDefaults.Options)!.Provenance.IsFormalSong) formal++;
            return new(scores, works, samples, formal, users);
        }
    }
    public LibraryLanguageSummary LanguageSummary()
    {
        lock (_gate)
        {
            using var connection = Connect();
            using var command = connection.CreateCommand();
            command.CommandText = BaseSql + $"""
                SELECT count(*),
                    COALESCE(sum(CASE WHEN {ChineseOrCantoneseTagPredicate} THEN 1 ELSE 0 END),0),
                    COALESCE(sum(CASE WHEN {PopularPriorityTagPredicate} AND {ChineseOrCantoneseTagPredicate} THEN 1 ELSE 0 END),0),
                    COALESCE(sum(CASE WHEN EXISTS (
                        SELECT 1 FROM json_each(metadata_json, '$.provenance.languageTags') AS language_tag
                        WHERE lower(CAST(language_tag.value AS TEXT)) = 'en'
                           OR lower(CAST(language_tag.value AS TEXT)) LIKE 'en-%'
                    ) THEN 1 ELSE 0 END),0),
                    COALESCE(sum(CASE WHEN NOT EXISTS (
                        SELECT 1 FROM json_each(metadata_json, '$.provenance.languageTags') AS language_tag
                    ) THEN 1 ELSE 0 END),0)
                FROM base
                """;
            using var reader = command.ExecuteReader();
            if (!reader.Read()) throw new FormatException("曲库语种摘要读取失败；未修改目录或用户数据。");
            int total = Convert.ToInt32(reader.GetInt64(0));
            int chinesePop = Convert.ToInt32(reader.GetInt64(1));
            int chinesePopular = Convert.ToInt32(reader.GetInt64(2));
            int explicitEnglish = Convert.ToInt32(reader.GetInt64(3));
            int unknownLanguage = Convert.ToInt32(reader.GetInt64(4));
            return new(chinesePop, chinesePopular, explicitEnglish, unknownLanguage, total);
        }
    }
    public string ResolvePath(LibraryEntry entry) => LibraryCatalog.Resolve(entry.BuiltIn ? BuiltInDirectory : DataDirectory, entry.RelativePath);
    public SongDocument LoadSong(LibraryEntry entry)
    {
        string path = ResolvePath(entry);
        if (entry.ResourceHash.Length > 0 && !LibraryCatalog.HashFile(path).Equals(entry.ResourceHash, StringComparison.OrdinalIgnoreCase)) throw new FormatException("谱文件哈希不符；文件未修改，请检查资源或另存修订版。");
        var song = SongParser.Read(path); Interlocked.Increment(ref _songReads); return song;
    }
    private int _songReads;
    public int ActualSongReads => Volatile.Read(ref _songReads);
    public (LibraryEntry Entry, bool Duplicate) Import(string source)
    {
        string id = Guid.NewGuid().ToString("N"); string extension = Path.GetExtension(source).ToLowerInvariant();
        string staged = Path.Combine(DataDirectory, "originals", id + extension);
        string normalized = Path.Combine(DataDirectory, "scores", id + ".json");
        bool created = false;
        try
        {
            if (new FileInfo(source).Length > SongParser.MaxFileBytes) throw new FormatException("单个谱子不能超过 16 MiB。");
            File.Copy(source, staged, false); created = true;
            var song = SongParser.Read(staged); string hash = LibraryCatalog.HashFile(staged);
            lock (_gate)
            {
                using var c = Connect(); using var duplicate = c.CreateCommand();
                duplicate.CommandText = "SELECT id FROM builtin.entries WHERE original_hash=$hash UNION ALL SELECT id FROM main.entries WHERE original_hash=$hash LIMIT 1"; duplicate.Parameters.AddWithValue("$hash", hash);
                if (duplicate.ExecuteScalar() is string old) { File.Delete(staged); created = false; return (Find(old)!, true); }
                string json = SongParser.ToJson(song, false); File.WriteAllText(normalized, json, new System.Text.UTF8Encoding(false));
                var entry = Create(song, Path.Combine("scores", id + ".json"), hash, false); entry.Id = entry.CatalogId = id; entry.ResourceHash = LibraryCatalog.HashFile(normalized);
                using var transaction = c.BeginTransaction(); LibraryCatalog.Insert(c, transaction, entry); WriteState(c, transaction, entry); transaction.Commit();
                return (Observe(entry), false);
            }
        }
        catch
        {
            // Only brand-new UUID files created by this import are rolled back, never the user's source.
            if (created && File.Exists(staged)) File.Delete(staged);
            if (File.Exists(normalized)) File.Delete(normalized); throw;
        }
    }
    public LibraryEntry AddSong(SongDocument song)
    {
        SongParser.Validate(song); song.Provenance.Validate();
        string id = Guid.NewGuid().ToString("N"), relative = Path.Combine("scores", id + ".json"), path = Path.Combine(DataDirectory, relative);
        string json = SongParser.ToJson(song, false); File.WriteAllText(path, json, new System.Text.UTF8Encoding(false));
        try
        {
            var entry = Create(song, relative, LibraryCatalog.HashFile(path), false); entry.Id = entry.CatalogId = id;
            lock (_gate) { using var c = Connect(); using var tx = c.BeginTransaction(); LibraryCatalog.Insert(c, tx, entry); WriteState(c, tx, entry); tx.Commit(); return Observe(entry); }
        }
        catch { File.Delete(path); throw; }
    }
    public static LibraryEntry Create(SongDocument song, string relative, string originalHash, bool builtin) => new()
    {
        Title = song.Title, Author = song.Author, Category = song.Category, RelativePath = relative, Hash = originalHash,
        ResourceHash = originalHash, BuiltIn = builtin, DurationMs = song.DurationMs, NotesCount = song.Notes.Count, Bpm = song.Bpm, Provenance = song.Provenance
    };
    private static void WriteState(SqliteConnection connection, SqliteTransaction transaction, LibraryEntry entry)
    {
        entry.Options.Validate();
        string key = entry.CatalogId.Length > 0 ? entry.CatalogId : entry.Id;
        using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = """
            INSERT INTO user_state(catalog_id,legacy_id,favorite,in_queue,last_played_ms,state_json) VALUES($id,$legacy,$favorite,$queue,$played,$json)
            ON CONFLICT(catalog_id) DO UPDATE SET legacy_id=excluded.legacy_id,favorite=excluded.favorite,in_queue=excluded.in_queue,last_played_ms=excluded.last_played_ms,state_json=excluded.state_json;
            """;
        command.Parameters.AddWithValue("$id", key); command.Parameters.AddWithValue("$legacy", entry.Id == key ? DBNull.Value : entry.Id);
        command.Parameters.AddWithValue("$favorite", entry.Favorite ? 1 : 0); command.Parameters.AddWithValue("$queue", entry.InQueue ? 1 : 0);
        command.Parameters.AddWithValue("$played", entry.LastPlayedAt is { } last ? last.ToUnixTimeMilliseconds() : DBNull.Value);
        command.Parameters.AddWithValue("$json", StateJson(entry)); command.ExecuteNonQuery();
    }
    public void Save(LibraryEntry entry) => SaveMany([entry]);
    public void SaveMany(IEnumerable<LibraryEntry> entries)
    {
        var items = entries.DistinctBy(e => e.CatalogId).ToList();
        lock (_gate)
        {
            var before = items.ToDictionary(e => e.CatalogId, e => _observed.TryGetValue(e.CatalogId, out var value) ? value.State : null);
            try
            {
                using var c = Connect(); using var tx = c.BeginTransaction();
                foreach (var entry in items)
                {
                    using var exists = c.CreateCommand(); exists.Transaction = tx;
                    exists.CommandText = "SELECT EXISTS(SELECT 1 FROM builtin.entries WHERE id=$id UNION ALL SELECT 1 FROM main.entries WHERE id=$id)";
                    exists.Parameters.AddWithValue("$id", entry.CatalogId);
                    if (Convert.ToInt32(exists.ExecuteScalar()) == 0) throw new FormatException("不能保存不存在的曲库条目。");
                    WriteState(c, tx, entry);
                }
                tx.Commit();
                foreach (var entry in items)
                {
                    _ = Observe(entry);
                    _observed[entry.CatalogId] = (entry, StateJson(entry));
                }
            }
            catch
            {
                foreach (var entry in items) if (before[entry.CatalogId] is { } state) ApplyState(entry, state);
                throw;
            }
        }
    }
    public void Save()
    {
        // Compatibility only: compare materialized entries; never rewrite the complete catalogue.
        lock (_gate) SaveMany(_observed.Values.Where(p => p.State != StateJson(p.Entry)).Select(p => p.Entry).ToList());
    }
    public IReadOnlyList<PlaylistInfo> Playlists()
    {
        lock (_gate) { using var c = Connect(); using var command = c.CreateCommand(); command.CommandText = "SELECT p.id,p.name,count(i.catalog_id) FROM playlists p LEFT JOIN playlist_items i ON i.playlist_id=p.id GROUP BY p.id ORDER BY p.created_ms,p.id"; using var reader = command.ExecuteReader(); var rows = new List<PlaylistInfo>(); while (reader.Read()) rows.Add(new(reader.GetString(0), reader.GetString(1), reader.GetInt32(2))); return rows; }
    }
    private static string PlaylistName(string name)
    {
        name = name.Trim(); if (name.Length is < 1 or > 80 || string.IsNullOrWhiteSpace(LibrarySearch.Normalize(name))) throw new FormatException("歌单名称须包含文字，长度 1–80 个字符。"); return name;
    }
    public PlaylistInfo CreatePlaylist(string name)
    {
        name = PlaylistName(name); string id = Guid.NewGuid().ToString("N");
        lock (_gate) { using var c = Connect(); using var command = c.CreateCommand(); command.CommandText = "INSERT INTO playlists VALUES($id,$name,$key,$time)"; command.Parameters.AddWithValue("$id", id); command.Parameters.AddWithValue("$name", name); command.Parameters.AddWithValue("$key", LibrarySearch.Normalize(name)); command.Parameters.AddWithValue("$time", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); command.ExecuteNonQuery(); }
        return new(id, name, 0);
    }
    public void RenamePlaylist(string id, string name)
    {
        name = PlaylistName(name);
        lock (_gate) { using var c = Connect(); using var command = c.CreateCommand(); command.CommandText = "UPDATE playlists SET name=$name,name_key=$key WHERE id=$id"; command.Parameters.AddWithValue("$id", id); command.Parameters.AddWithValue("$name", name); command.Parameters.AddWithValue("$key", LibrarySearch.Normalize(name)); if (command.ExecuteNonQuery() != 1) throw new FormatException("歌单不存在。"); }
    }
    public void DeletePlaylist(string id)
    {
        lock (_gate) { using var c = Connect(); using var command = c.CreateCommand(); command.CommandText = "DELETE FROM playlists WHERE id=$id"; command.Parameters.AddWithValue("$id", id); command.ExecuteNonQuery(); }
    }
    public void AddToPlaylist(string playlist, IEnumerable<LibraryEntry> entries)
    {
        var items = entries.DistinctBy(e => e.CatalogId).ToList();
        lock (_gate)
        {
            using var c = Connect(); using var tx = c.BeginTransaction();
            using var position = c.CreateCommand(); position.Transaction = tx; position.CommandText = "SELECT COALESCE(max(position)+1,0) FROM playlist_items WHERE playlist_id=$id"; position.Parameters.AddWithValue("$id", playlist); int next = Convert.ToInt32(position.ExecuteScalar());
            foreach (var entry in items)
            {
                using var exists = c.CreateCommand(); exists.Transaction = tx;
                exists.CommandText = "SELECT EXISTS(SELECT 1 FROM builtin.entries WHERE id=$id UNION ALL SELECT 1 FROM main.entries WHERE id=$id)";
                exists.Parameters.AddWithValue("$id", entry.CatalogId);
                if (Convert.ToInt32(exists.ExecuteScalar()) == 0) throw new FormatException("歌单只能加入曲库内的现有谱目。");
                using var command = c.CreateCommand(); command.Transaction = tx; command.CommandText = "INSERT OR IGNORE INTO playlist_items VALUES($playlist,$id,$position)"; command.Parameters.AddWithValue("$playlist", playlist); command.Parameters.AddWithValue("$id", entry.CatalogId); command.Parameters.AddWithValue("$position", next++); command.ExecuteNonQuery();
            }
            tx.Commit();
        }
    }
    public void RemoveFromPlaylist(string playlist, IEnumerable<LibraryEntry> entries)
    {
        lock (_gate) { using var c = Connect(); using var tx = c.BeginTransaction(); foreach (var entry in entries) { using var command = c.CreateCommand(); command.Transaction = tx; command.CommandText = "DELETE FROM playlist_items WHERE playlist_id=$playlist AND catalog_id=$id"; command.Parameters.AddWithValue("$playlist", playlist); command.Parameters.AddWithValue("$id", entry.CatalogId); command.ExecuteNonQuery(); } tx.Commit(); }
    }
    private sealed class EntryView(LibraryStore store) : IReadOnlyList<LibraryEntry>
    {
        public int Count => store.Count;
        public LibraryEntry this[int index] => store.Query(new(Offset: index, Limit: 1)).Items.FirstOrDefault() ?? throw new ArgumentOutOfRangeException(nameof(index));
        public IEnumerator<LibraryEntry> GetEnumerator() => store.Enumerate(new()).GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
