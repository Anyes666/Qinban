using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Data.Sqlite;
namespace QinBan.Core;

public static class LibraryCatalog
{
    public const int SchemaVersion = 1;
    public const string FileName = "catalog.db";
    internal const string Schema = """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE entries(id TEXT PRIMARY KEY, work_id TEXT NOT NULL, relative_path TEXT NOT NULL,
            content_hash TEXT NOT NULL, original_hash TEXT NOT NULL, metadata_json TEXT NOT NULL);
        CREATE TABLE search_index(entry_id TEXT PRIMARY KEY REFERENCES entries(id), title_key TEXT NOT NULL,
            author_key TEXT NOT NULL, search_text TEXT NOT NULL, pinyin TEXT NOT NULL, initials TEXT NOT NULL,
            sort_title TEXT NOT NULL, duration REAL NOT NULL, added_ms INTEGER NOT NULL, provider TEXT NOT NULL,
            timing_verified INTEGER NOT NULL, completeness TEXT NOT NULL, human_reviewed INTEGER NOT NULL);
        CREATE INDEX search_title ON search_index(title_key);
        CREATE INDEX search_pinyin ON search_index(pinyin);
        CREATE INDEX search_sort ON search_index(sort_title,entry_id);
        CREATE INDEX search_added ON search_index(added_ms,entry_id);
        CREATE INDEX search_duration ON search_index(duration,entry_id);
        CREATE INDEX entries_work ON entries(work_id);
        CREATE INDEX entries_original ON entries(original_hash);
        CREATE INDEX entries_path ON entries(relative_path);
        """;
    public static void Build(string destination, IEnumerable<LibraryEntry> entries, string? resourceRoot = null, bool syntheticOnly = false)
    {
        string target = Path.GetFullPath(destination); Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        string temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var items = entries.ToList();
        if (items.Count > 100_000 || items.Select(e => e.Id).Distinct().Count() != items.Count) throw new FormatException("目录条目超限或 ID 重复。");
        foreach (var entry in items)
        {
            ValidateEntry(entry);
            if (syntheticOnly && !entry.Provenance.Synthetic) throw new FormatException("无资源检查模式仅允许明确标记的合成压力条目。");
            if (!syntheticOnly)
            {
                if (resourceRoot == null) throw new ArgumentException("建库必须提供资源根目录。");
                string source = Resolve(resourceRoot, entry.RelativePath);
                if (!File.Exists(source) || !HashFile(source).Equals(entry.ResourceHash.Length > 0 ? entry.ResourceHash : entry.Hash, StringComparison.OrdinalIgnoreCase)) throw new FormatException("目录资源缺失或哈希不符：" + entry.RelativePath);
            }
        }
        using (var connection = Open(temporary, SqliteOpenMode.ReadWriteCreate))
        {
            using var transaction = connection.BeginTransaction();
            Execute(connection, Schema, transaction);
            foreach (var entry in items) Insert(connection, transaction, entry);
            using var command = connection.CreateCommand(); command.Transaction = transaction;
            command.CommandText = "INSERT INTO meta(key,value) VALUES('schema',$schema),('synthetic',$synthetic)";
            command.Parameters.AddWithValue("$schema", SchemaVersion.ToString()); command.Parameters.AddWithValue("$synthetic", syntheticOnly ? "1" : "0"); command.ExecuteNonQuery();
            transaction.Commit();
        }
        // The caller owns this generated catalogue. Existing application/user resources are never changed.
        File.Move(temporary, target, true);
    }
    internal static SqliteConnection Open(string path, SqliteOpenMode mode)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = mode, Pooling = false, DefaultTimeout = 5 }.ToString());
        connection.Open(); Execute(connection, "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;"); return connection;
    }
    internal static void Execute(SqliteConnection connection, string sql, SqliteTransaction? transaction = null)
    {
        using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; command.ExecuteNonQuery();
    }
    internal static void Insert(SqliteConnection connection, SqliteTransaction transaction, LibraryEntry entry, string schema = "main")
    {
        var keys = LibrarySearch.Build(entry);
        using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = $"""
            INSERT INTO {schema}.entries(id,work_id,relative_path,content_hash,original_hash,metadata_json) VALUES($id,$work,$path,$hash,$original,$json);
            INSERT INTO {schema}.search_index VALUES($id,$title,$author,$text,$pinyin,$initials,$sort,$duration,$added,$provider,$timing,$complete,$human);
            """;
        command.Parameters.AddWithValue("$id", entry.CatalogId.Length > 0 ? entry.CatalogId : entry.Id);
        command.Parameters.AddWithValue("$work", entry.Provenance.WorkId.Length > 0 ? entry.Provenance.WorkId : entry.Id);
        command.Parameters.AddWithValue("$path", entry.RelativePath); command.Parameters.AddWithValue("$hash", entry.ResourceHash.Length > 0 ? entry.ResourceHash : entry.Hash);
        command.Parameters.AddWithValue("$original", entry.Hash);
        command.Parameters.AddWithValue("$json", JsonSerializer.Serialize(entry, JsonDefaults.Options));
        command.Parameters.AddWithValue("$title", keys.Title); command.Parameters.AddWithValue("$author", keys.Author);
        command.Parameters.AddWithValue("$text", keys.Text); command.Parameters.AddWithValue("$pinyin", keys.Pinyin);
        command.Parameters.AddWithValue("$initials", keys.Initials); command.Parameters.AddWithValue("$sort", keys.SortTitle);
        command.Parameters.AddWithValue("$duration", entry.DurationMs); command.Parameters.AddWithValue("$added", entry.AddedAt.ToUnixTimeMilliseconds());
        command.Parameters.AddWithValue("$provider", entry.Provenance.Provider); command.Parameters.AddWithValue("$timing", entry.Provenance.TimingStatus == "source-compared" ? 1 : 0);
        command.Parameters.AddWithValue("$complete", entry.Provenance.Completeness); command.Parameters.AddWithValue("$human", entry.Provenance.MusicReview == "human-reviewed" ? 1 : 0);
        command.ExecuteNonQuery();
    }
    internal static void ValidateEntry(LibraryEntry entry)
    {
        if (string.IsNullOrWhiteSpace(entry.Id) || entry.Id.Length > 256 || string.IsNullOrWhiteSpace(entry.Title)
            || entry.Title.Length > 1000 || entry.Author.Length > 1000 || entry.Category.Length > 1000
            || !double.IsFinite(entry.DurationMs) || entry.DurationMs < 0 || entry.DurationMs > SongParser.MaxDurationMs
            || !double.IsFinite(entry.Bpm) || entry.Bpm <= 0 || entry.NotesCount is < 0 or > SongParser.MaxNotes)
            throw new FormatException("曲库条目元数据无效。");
        entry.Options.Validate(); entry.Provenance.Validate();
        _ = Resolve(Path.GetTempPath(), entry.RelativePath);
    }
    public static string Resolve(string root, string relative)
    {
        string basePath = Path.GetFullPath(root);
        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative)) throw new FormatException("谱资源路径必须是目录内的相对路径。");
        string full = Path.GetFullPath(Path.Combine(basePath, relative));
        string within = Path.GetRelativePath(basePath, full);
        if (within == ".." || within.StartsWith(".." + Path.DirectorySeparatorChar) || Path.IsPathRooted(within)) throw new FormatException("曲库包含越界路径，已拒绝读取。");
        return full;
    }
    public static string HashFile(string path) { using var stream = File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(stream)); }
}
