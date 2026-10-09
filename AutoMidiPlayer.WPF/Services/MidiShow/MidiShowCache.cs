using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using AutoMidiPlayer.Data;

using AutoMidiPlayer.WPF.Services.OnlineMidi;

namespace AutoMidiPlayer.WPF.Services.MidiShow;

/// <summary>
/// Persistent disk cache for the Discover page. Stores MIDI summaries, details, downloaded
/// MIDI files and avatar images under <see cref="AppPaths.DiscoverCacheDirectory"/>. All I/O
/// is resilient — cache misses or corrupt files silently fall back to the network.
///
/// Supports:
///   • TTL-based expiry (configurable, default 24 h for metadata)
///   • LRU eviction when <c>CacheMaxSizeMB</c> is set (> 0)
///   • Scheduled auto-clean (daily / weekly / monthly / never)
///   • Manual clear-all
/// </summary>
public static class MidiShowCache
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    /// <summary>
    /// Default TTL for summary and detail metadata. MIDI files and avatars never expire
    /// (they are immutable content-addressed resources).
    /// </summary>
    private static readonly TimeSpan MetadataTtl = TimeSpan.FromHours(24);

    /// <summary>
    /// Shorter TTL for page listings (search and browse) to keep the latest uploads fresh.
    /// </summary>
    private static readonly TimeSpan PageTtl = TimeSpan.FromHours(1);

    // File names inside each midi/{id}/ folder.
    private const string SummaryFileName = "summary.json";
    private const string DetailsFileName = "details.json";
    private const string MidiFileName = "file.mid";

    #region Page Listings

    public static async Task SaveBrowsePageAsync(int page, string sort, string category, OnlineMidiPageResult result)
    {
        try
        {
            var fileName = $"browse_p{page}_s{sort}_c{category}.json".Replace(" ", "_");
            await SavePageInternalAsync(fileName, result);
        }
        catch { }
    }

    public static OnlineMidiPageResult? TryLoadBrowsePage(int page, string sort, string category)
    {
        var fileName = $"browse_p{page}_s{sort}_c{category}.json".Replace(" ", "_");
        return TryLoadPageInternal(fileName);
    }

    public static async Task SaveSearchPageAsync(string query, int page, string sort, OnlineMidiPageResult result)
    {
        try
        {
            // Hash the query to avoid invalid file characters
            var queryHash = HashUrl(query.ToLowerInvariant());
            var fileName = $"search_{queryHash}_p{page}_s{sort}.json";
            await SavePageInternalAsync(fileName, result);
        }
        catch { }
    }

    public static OnlineMidiPageResult? TryLoadSearchPage(string query, int page, string sort)
    {
        var queryHash = HashUrl(query.ToLowerInvariant());
        var fileName = $"search_{queryHash}_p{page}_s{sort}.json";
        return TryLoadPageInternal(fileName);
    }

    private static async Task SavePageInternalAsync(string fileName, OnlineMidiPageResult result)
    {
        AppPaths.EnsureDiscoverCacheDirectories();
        var path = Path.Combine(AppPaths.DiscoverCacheDirectory, fileName);
        var entry = new CacheEntry<CachedOnlineMidiPageResult>
        {
            Data = new CachedOnlineMidiPageResult
            {
                Items = result.Items.Select(CachedOnlineMidiItem.From).ToList(),
                StatusText = result.StatusText
            },
            CachedAtUtc = DateTime.UtcNow
        };
        var json = JsonSerializer.Serialize(entry, JsonOptions);
        await File.WriteAllTextAsync(path, json);
    }

    private static OnlineMidiPageResult? TryLoadPageInternal(string fileName)
    {
        try
        {
            var path = Path.Combine(AppPaths.DiscoverCacheDirectory, fileName);
            if (!File.Exists(path))
                return null;

            var json = File.ReadAllText(path);
            
            // Try to deserialize as the new format first.
            try
            {
                var entry = JsonSerializer.Deserialize<CacheEntry<CachedOnlineMidiPageResult>>(json, JsonOptions);
                if (entry?.Data != null)
                {
                    if (DateTime.UtcNow - entry.CachedAtUtc > PageTtl)
                        return null;

                    TouchFile(path);
                    var items = entry.Data.Items.ConvertAll(d => d.ToItem());
                    return new OnlineMidiPageResult(items, entry.Data.StatusText ?? "");
                }
            }
            catch
            {
                // Fallback for old cache format
                var oldEntry = JsonSerializer.Deserialize<CacheEntry<List<CachedOnlineMidiItem>>>(json, JsonOptions);
                if (oldEntry?.Data != null)
                {
                    if (DateTime.UtcNow - oldEntry.CachedAtUtc > PageTtl)
                        return null;

                    TouchFile(path);
                    var items = oldEntry.Data.ConvertAll(d => d.ToItem());
                    return new OnlineMidiPageResult(items, "");
                }
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    #endregion

    #region Summary

    /// <summary>Persists a single <see cref="OnlineMidiItem"/> summary to disk.</summary>
    public static async Task SaveSummaryAsync(OnlineMidiItem item)
    {
        try
        {
            var dir = EnsureMidiDir(item.Id);
            var entry = new CacheEntry<CachedOnlineMidiItem>
            {
                Data = CachedOnlineMidiItem.From(item),
                CachedAtUtc = DateTime.UtcNow
            };
            var json = JsonSerializer.Serialize(entry, JsonOptions);
            await File.WriteAllTextAsync(Path.Combine(dir, SummaryFileName), json);
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: failed to save summary for {item.Id}: {ex.Message}");
        }
    }

    /// <summary>Persists a batch of listing results to disk (fire-and-forget).</summary>
    public static async Task SaveSummariesAsync(IEnumerable<OnlineMidiItem> items)
    {
        foreach (var item in items)
        {
            if (!string.IsNullOrEmpty(item.Id) && !item.Id.StartsWith("skeleton_"))
                await SaveSummaryAsync(item);
        }
    }

    /// <summary>
    /// Loads a cached summary for the given MIDI id. Returns null when the file doesn't
    /// exist or has expired.
    /// </summary>
    public static OnlineMidiItem? TryLoadSummary(string id)
    {
        try
        {
            var path = Path.Combine(AppPaths.DiscoverMidiCacheDirectory, id, SummaryFileName);
            if (!File.Exists(path))
                return null;

            var json = File.ReadAllText(path);
            var entry = JsonSerializer.Deserialize<CacheEntry<CachedOnlineMidiItem>>(json, JsonOptions);
            if (entry?.Data is null || DateTime.UtcNow - entry.CachedAtUtc > MetadataTtl)
                return null;

            TouchFile(path);
            return entry.Data.ToItem();
        }
        catch
        {
            return null;
        }
    }

    #endregion

    #region Details

    /// <summary>Persists full MIDI details to disk.</summary>
    public static async Task SaveDetailsAsync(MidiShowDetails details)
    {
        try
        {
            var dir = EnsureMidiDir(details.Id);
            var entry = new CacheEntry<CachedMidiShowDetails>
            {
                Data = CachedMidiShowDetails.From(details),
                CachedAtUtc = DateTime.UtcNow
            };
            var json = JsonSerializer.Serialize(entry, JsonOptions);
            await File.WriteAllTextAsync(Path.Combine(dir, DetailsFileName), json);
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: failed to save details for {details.Id}: {ex.Message}");
        }
    }

    /// <summary>
    /// Loads cached details for the given MIDI id. Returns null when the file doesn't
    /// exist or has expired.
    /// </summary>
    public static MidiShowDetails? TryLoadDetails(string id)
    {
        try
        {
            var path = Path.Combine(AppPaths.DiscoverMidiCacheDirectory, id, DetailsFileName);
            if (!File.Exists(path))
                return null;

            var json = File.ReadAllText(path);
            var entry = JsonSerializer.Deserialize<CacheEntry<CachedMidiShowDetails>>(json, JsonOptions);
            if (entry?.Data is null || DateTime.UtcNow - entry.CachedAtUtc > MetadataTtl)
                return null;

            TouchFile(path);
            return entry.Data.ToDetails();
        }
        catch
        {
            return null;
        }
    }

    #endregion

    #region MIDI file

    /// <summary>Caches downloaded MIDI bytes. No TTL — MIDI content doesn't change.</summary>
    public static async Task SaveMidiFileAsync(string id, byte[] data)
    {
        try
        {
            var dir = EnsureMidiDir(id);
            await File.WriteAllBytesAsync(Path.Combine(dir, MidiFileName), data);
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: failed to save MIDI file for {id}: {ex.Message}");
        }
    }

    /// <summary>Returns cached MIDI bytes, or null if not cached.</summary>
    public static byte[]? TryLoadMidiFile(string id)
    {
        try
        {
            var path = Path.Combine(AppPaths.DiscoverMidiCacheDirectory, id, MidiFileName);
            if (!File.Exists(path))
                return null;

            TouchFile(path);
            return File.ReadAllBytes(path);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Returns the absolute file path for a cached MIDI file by its ID.</summary>
    public static string GetMidiFilePath(string id) => Path.Combine(AppPaths.DiscoverMidiCacheDirectory, id, MidiFileName);

    #endregion

    #region Avatar

    /// <summary>
    /// Returns the local file path for a cached avatar, or null if not cached.
    /// </summary>
    public static string? TryGetAvatarPath(string url)
    {
        try
        {
            var hash = HashUrl(url);
            var path = Path.Combine(AppPaths.DiscoverAvatarCacheDirectory, hash);
            if (File.Exists(path))
            {
                TouchFile(path);
                return path;
            }
            return null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Saves avatar image bytes to disk, keyed by URL hash. Returns the local file path.
    /// </summary>
    public static async Task<string?> SaveAvatarAsync(string url, byte[] data)
    {
        try
        {
            AppPaths.EnsureDiscoverCacheDirectories();
            var hash = HashUrl(url);
            var path = Path.Combine(AppPaths.DiscoverAvatarCacheDirectory, hash);
            await File.WriteAllBytesAsync(path, data);
            return path;
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: failed to save avatar: {ex.Message}");
            return null;
        }
    }

    #endregion

    #region Cache management

    /// <summary>
    /// Calculates the total size of the discover cache in bytes.
    /// </summary>
    public static long GetCacheSizeBytes()
    {
        try
        {
            if (!Directory.Exists(AppPaths.DiscoverCacheDirectory))
                return 0;

            return new DirectoryInfo(AppPaths.DiscoverCacheDirectory)
                .EnumerateFiles("*", SearchOption.AllDirectories)
                .Sum(f => f.Length);
        }
        catch
        {
            return 0;
        }
    }

    /// <summary>Formats a byte count as a human-readable string (KB, MB, GB).</summary>
    public static string FormatSize(long bytes)
    {
        if (bytes < 1024)
            return $"{bytes} B";
        if (bytes < 1024 * 1024)
            return $"{bytes / 1024.0:F1} KB";
        if (bytes < 1024L * 1024 * 1024)
            return $"{bytes / (1024.0 * 1024):F1} MB";
        return $"{bytes / (1024.0 * 1024 * 1024):F2} GB";
    }

    /// <summary>Deletes all cached data (metadata, MIDI files, avatars).</summary>
    public static void ClearAll()
    {
        try
        {
            if (Directory.Exists(AppPaths.DiscoverCacheDirectory))
            {
                Directory.Delete(AppPaths.DiscoverCacheDirectory, recursive: true);
                Logger.LogStep("MIDISHOW_CACHE", "Cache cleared.");
            }
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: failed to clear: {ex.Message}");
        }
    }

    /// <summary>
    /// Runs LRU eviction: deletes least-recently-accessed files until the cache is under
    /// <paramref name="maxSizeMb"/> MB. A value of 0 means unlimited (no eviction).
    /// </summary>
    public static void EvictLru(int maxSizeMb)
    {
        if (maxSizeMb <= 0)
            return;

        try
        {
            if (!Directory.Exists(AppPaths.DiscoverCacheDirectory))
                return;

            var maxBytes = (long)maxSizeMb * 1024 * 1024;
            var currentSize = GetCacheSizeBytes();
            if (currentSize <= maxBytes)
                return;

            // Collect all files sorted by last access time (oldest first).
            var files = new DirectoryInfo(AppPaths.DiscoverCacheDirectory)
                .EnumerateFiles("*", SearchOption.AllDirectories)
                .OrderBy(f => f.LastAccessTimeUtc)
                .ToList();

            foreach (var file in files)
            {
                if (currentSize <= maxBytes)
                    break;

                try
                {
                    currentSize -= file.Length;
                    file.Delete();

                    // Clean up empty parent directories.
                    var parent = file.Directory;
                    if (parent is { Exists: true } && !parent.EnumerateFileSystemInfos().Any())
                        parent.Delete();
                }
                catch
                {
                    // Skip files that can't be deleted (in use, etc.)
                }
            }

            Logger.LogStep("MIDISHOW_CACHE_LRU", $"Evicted to {FormatSize(currentSize)} (limit {maxSizeMb} MB)");
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: LRU eviction failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Runs scheduled auto-clean based on the configured interval. Checks whether
    /// enough time has elapsed since the last clean and, if so, deletes all cached data.
    /// </summary>
    /// <param name="intervalSetting">0 = daily, 1 = weekly, 2 = monthly, 3 = never.</param>
    public static void RunAutoCleanIfDue(int intervalSetting)
    {
        if (intervalSetting == 3) // never
            return;

        try
        {
            var markerPath = Path.Combine(AppPaths.DiscoverCacheDirectory, ".last_clean");
            DateTime lastClean;

            if (File.Exists(markerPath) && DateTime.TryParse(File.ReadAllText(markerPath).Trim(), out var parsed))
                lastClean = parsed.ToUniversalTime();
            else
                lastClean = DateTime.MinValue;

            var interval = intervalSetting switch
            {
                0 => TimeSpan.FromDays(1),
                1 => TimeSpan.FromDays(7),
                _ => TimeSpan.FromDays(30) // 2 = monthly (default)
            };

            if (DateTime.UtcNow - lastClean < interval)
                return;

            Logger.LogStep("MIDISHOW_CACHE_AUTOCLEAN", $"Interval={intervalSetting} last={lastClean:o}");
            ClearAll();

            // Re-create the directory and write the marker.
            AppPaths.EnsureDiscoverCacheDirectories();
            File.WriteAllText(markerPath, DateTime.UtcNow.ToString("o"));
        }
        catch (Exception ex)
        {
            Logger.Log($"Cache: auto-clean failed: {ex.Message}");
        }
    }

    #endregion

    #region Helpers

    /// <summary>Ensures the per-MIDI cache directory exists and returns its path.</summary>
    private static string EnsureMidiDir(string id)
    {
        AppPaths.EnsureDiscoverCacheDirectories();
        var dir = Path.Combine(AppPaths.DiscoverMidiCacheDirectory, id);
        if (!Directory.Exists(dir))
            Directory.CreateDirectory(dir);
        return dir;
    }

    /// <summary>Deterministic hash of a URL for avatar file naming.</summary>
    private static string HashUrl(string url)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(url));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    /// <summary>
    /// Updates the last-access time of a file so LRU eviction keeps frequently-used
    /// entries alive. Silently ignores failures.
    /// </summary>
    private static void TouchFile(string path)
    {
        try { File.SetLastAccessTimeUtc(path, DateTime.UtcNow); }
        catch { /* ignore */ }
    }

    /// <summary>
    /// Extracts the numeric MIDI id from a MidiShow page URL.
    /// e.g. "https://www.midishow.com/en/midi/251160.html" → "251160".
    /// </summary>
    public static string? ExtractIdFromUrl(string pageUrl)
    {
        if (string.IsNullOrEmpty(pageUrl))
            return null;

        var match = System.Text.RegularExpressions.Regex.Match(pageUrl, @"(\d+)(?:\.html)?$");
        return match.Success ? match.Groups[1].Value : null;
    }

    #endregion
}

