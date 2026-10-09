using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using AutoMidiPlayer.Data;
using AutoMidiPlayer.WPF.Services.MidiShow;

namespace AutoMidiPlayer.WPF.Services.OnlineMidi;

public static class NanoMidiCache
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private static readonly TimeSpan PageTtl = TimeSpan.FromHours(1);

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
        if (!Directory.Exists(AppPaths.NanoMidiCacheDirectory))
            Directory.CreateDirectory(AppPaths.NanoMidiCacheDirectory);

        var path = Path.Combine(AppPaths.NanoMidiCacheDirectory, fileName);
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
            var path = Path.Combine(AppPaths.NanoMidiCacheDirectory, fileName);
            if (!File.Exists(path))
                return null;

            var json = File.ReadAllText(path);
            
            var entry = JsonSerializer.Deserialize<CacheEntry<CachedOnlineMidiPageResult>>(json, JsonOptions);
            if (entry?.Data != null)
            {
                if (DateTime.UtcNow - entry.CachedAtUtc > PageTtl)
                    return null;

                File.SetLastAccessTimeUtc(path, DateTime.UtcNow);
                var items = entry.Data.Items.ConvertAll(d =>
                {
                    d.ProviderSupportsTags = false;
                    return d.ToItem();
                });
                return new OnlineMidiPageResult(items, entry.Data.StatusText ?? "");
            }
            return null;
        }
        catch
        {
            return null;
        }
    }

    private static string HashUrl(string input)
    {
        var bytes = Encoding.UTF8.GetBytes(input);
        var hashBytes = MD5.HashData(bytes);
        return Convert.ToHexString(hashBytes).ToLowerInvariant();
    }
}
