using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AutoMidiPlayer.WPF.Services.OnlineMidi;

public class NanoMidiProvider : IOnlineMidiProvider
{
    private static readonly HttpClient Http = new HttpClient();

    static NanoMidiProvider()
    {
        Http.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36");
        Http.Timeout = TimeSpan.FromSeconds(30);
    }

    public string Id => "NanoMidi";
    public string DisplayName => "nanoMIDI";
    public bool RequiresAccount => false;
    public bool SupportsTags => false;

    public IReadOnlyList<FilterOption> CategoryOptions { get; } = new List<FilterOption>();

    public IReadOnlyList<FilterOption> SortOptions { get; } = new List<FilterOption>
    {
        new("Newest", "Newest", "ArrowTrending12"),
        new("Oldest", "Oldest", "Clock12"),
        new("Downloads", "Downloads", "ArrowDownload24"),
        new("Views", "Most viewed", "Eye24")
    };

    private async Task<List<OnlineMidiItem>> FetchPageAsync(int page, string? query, CancellationToken ct)
    {
        string url = $"https://api.nanomidi.net/api/v2/midiData?page={page}";
        if (!string.IsNullOrWhiteSpace(query))
        {
            url += $"&search={Uri.EscapeDataString(query)}";
        }

        using var response = await Http.GetAsync(url, ct);
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync(ct);
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        
        var items = new List<OnlineMidiItem>();
        if (root.TryGetProperty("data", out var documentsRaw) && documentsRaw.ValueKind == JsonValueKind.Array)
        {
            foreach (var element in documentsRaw.EnumerateArray())
            {
                try 
                {
                    var id = element.TryGetProperty("$id", out var pid) ? pid.GetString() ?? "" : "";
                    var name = element.TryGetProperty("name", out var pname) ? pname.GetString() ?? "" : "";
                    var uploader = element.TryGetProperty("uploader", out var puploader) ? puploader.GetString() ?? "" : "";
                    var downloads = element.TryGetProperty("downloads", out var pdown) ? pdown.GetRawText() : "0";
                    var views = element.TryGetProperty("views", out var pviews) ? pviews.GetRawText() : "0";
                    var bpm = element.TryGetProperty("bpm", out var pbpm) ? pbpm.GetRawText() : "";
                    
                    var sizeStr = "";
                    if (element.TryGetProperty("size", out var psize) && psize.TryGetInt32(out var sizeBytes)) {
                        sizeStr = (sizeBytes / 1024.0).ToString("0.00") + " KB";
                    }

                    var arranger = element.TryGetProperty("arranger", out var parr) ? parr.GetString() : "";
                    if (arranger == "null") arranger = "";
                    
                    var createdAt = element.TryGetProperty("$createdAt", out var pcreate) ? pcreate.GetString() ?? "" : "";
                    
                    var mf = element.TryGetProperty("midifile", out var pmf) ? pmf.GetString() ?? "" : "";
                    
                    string? thumbnailUrl = null;
                    if (element.TryGetProperty("imagefile", out var pimg) && pimg.ValueKind == JsonValueKind.String)
                    {
                        var img = pimg.GetString();
                        if (!string.IsNullOrEmpty(img))
                            thumbnailUrl = $"https://api.nanomidi.net/api/v2/images/{img}?size=100x100";
                    }

                    var artists = element.TryGetProperty("artists", out var partists) ? partists.GetString() : "";
                    var desc = string.IsNullOrWhiteSpace(artists) ? "" : $"Artist: {artists}";

                    items.Add(new OnlineMidiItem {
                        Id = id,
                        ProviderSupportsTags = false,
                        Title = name,
                        Uploader = uploader,
                        Downloads = downloads,
                        Views = views,
                        Bpm = bpm,
                        FileSize = sizeStr,
                        Arranger = arranger,
                        UploadDate = createdAt,
                        PageUrl = mf,
                        ThumbnailUrl = thumbnailUrl,
                        Description = desc
                    });
                }
                catch 
                {
                    // Skip malformed entries
                }
            }
        }
        
        return items;
    }

    public async Task<OnlineMidiPageResult> BrowseAsync(int page, string sortKey, string? categorySlug, bool forceRefresh, CancellationToken cancellationToken = default)
    {
        if (!forceRefresh)
        {
            var cached = NanoMidiCache.TryLoadBrowsePage(page, sortKey ?? "", categorySlug ?? "");
            if (cached != null)
                return cached;
        }

        var items = await FetchPageAsync(page, null, cancellationToken);
        
        // Apply sort locally only within the page, since nanoMIDI API doesn't support generic sorting types
        IEnumerable<OnlineMidiItem> sorted = items;
        if (sortKey == "Downloads")
            sorted = items.OrderByDescending(x => int.TryParse(x.Downloads, out var d) ? d : 0);
        else if (sortKey == "Views")
            sorted = items.OrderByDescending(x => int.TryParse(x.Views, out var v) ? v : 0);
        else if (sortKey == "Oldest")
            sorted = items.OrderBy(x => { DateTime.TryParse(x.UploadDate, out var dt); return dt; });
        else
            sorted = items.OrderByDescending(x => { DateTime.TryParse(x.UploadDate, out var dt); return dt; });

        var result = new OnlineMidiPageResult(sorted.ToList(), "");
        await NanoMidiCache.SaveBrowsePageAsync(page, sortKey ?? "", categorySlug ?? "", result);
        return result;
    }

    public async Task<OnlineMidiPageResult> SearchAsync(string query, int page, string sortKey, bool forceRefresh, CancellationToken cancellationToken = default)
    {
        if (!forceRefresh)
        {
            var cached = NanoMidiCache.TryLoadSearchPage(query, page, sortKey ?? "");
            if (cached != null)
                return cached;
        }

        var items = await FetchPageAsync(page, query, cancellationToken);

        // Apply sort locally only within the page, since nanoMIDI API doesn't support generic sorting types
        IEnumerable<OnlineMidiItem> sorted = items;
        if (sortKey == "Downloads")
            sorted = items.OrderByDescending(x => int.TryParse(x.Downloads, out var d) ? d : 0);
        else if (sortKey == "Views")
            sorted = items.OrderByDescending(x => int.TryParse(x.Views, out var v) ? v : 0);
        else if (sortKey == "Oldest")
            sorted = items.OrderBy(x => { DateTime.TryParse(x.UploadDate, out var dt); return dt; });
        else
            sorted = items.OrderByDescending(x => { DateTime.TryParse(x.UploadDate, out var dt); return dt; });

        var result = new OnlineMidiPageResult(sorted.ToList(), "");
        await NanoMidiCache.SaveSearchPageAsync(query, page, sortKey ?? "", result);
        return result;
    }

    public async Task<OnlineMidiDownloadResult> DownloadMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default)
    {
        var data = await DownloadPreviewMidiAsync(item, cancellationToken);
        return new OnlineMidiDownloadResult(data, item.Title);
    }

    public async Task<byte[]> DownloadPreviewMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default)
    {
        using var response = await Http.GetAsync($"https://api.nanomidi.net/api/midis/{item.PageUrl}", cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsByteArrayAsync(cancellationToken);
    }
}
