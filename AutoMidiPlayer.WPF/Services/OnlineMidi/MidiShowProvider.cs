using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using AutoMidiPlayer.WPF.Services.MidiShow;

namespace AutoMidiPlayer.WPF.Services.OnlineMidi;

public class MidiShowProvider : IOnlineMidiProvider
{
    private readonly MidiShowAccountPool _pool;
    
    public MidiShowProvider(MidiShowAccountPool pool)
    {
        _pool = pool;
    }

    public string Id => "MidiShow";
    public string DisplayName => "MidiShow";
    public bool RequiresAccount => true;
    public bool SupportsTags => true;

    public IReadOnlyList<FilterOption> CategoryOptions { get; } = new List<FilterOption>
    {
        new("", "All categories"),
        new("pop-music", "Pop Music"),
        new("game-music", "Anime / Game music"),
        new("movie_tv_soundtrack", "Film Score"),
        new("classical-music", "Classical Music"),
        new("electronic-music", "Electronic Music"),
        new("rock-and-roll", "Rock"),
        new("jazz-and-blues", "Jazz"),
        new("country-music", "Country Music"),
        new("rhythm-and-blues", "Rhythm & Blues"),
        new("hip-hop-and-rap", "Hip / Rap Music"),
        new("latin-music", "Latin"),
        new("national-music", "Folk Music"),
        new("folk-music", "Ballad"),
        new("easy-listening-music", "Easy Listening"),
        new("childrens-music", "Children's Music"),
        new("religious-music", "Religious Music"),
        new("other-music", "Other Music")
    };

    public IReadOnlyList<FilterOption> SortOptions { get; } = new List<FilterOption>
    {
        new("", "Newest", "ArrowTrending12"),
        new("time_asc", "Oldest", "Clock12"),
        new("popularity", "Most popular", "Fire24"),
        new("marks", "Highest rated", "StarEmphasis24")
    };

    public Task<OnlineMidiPageResult> BrowseAsync(int page, string sortKey, string? categorySlug, bool forceRefresh, CancellationToken cancellationToken = default)
    {
        return _pool.BrowseAsync(page, sortKey ?? "", categorySlug ?? "", forceRefresh, cancellationToken);
    }

    public Task<OnlineMidiPageResult> SearchAsync(string query, int page, string sortKey, bool forceRefresh, CancellationToken cancellationToken = default)
    {
        return _pool.SearchAsync(query, page, sortKey ?? "", forceRefresh, cancellationToken);
    }

    public async Task<OnlineMidiDownloadResult> DownloadMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default)
    {
        var result = await _pool.DownloadAsync(item.PageUrl);
        return new OnlineMidiDownloadResult(result.Data, result.Title, result.TrackNames);
    }

    public async Task<byte[]> DownloadPreviewMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default)
    {
        var result = await _pool.DownloadAsync(item.PageUrl);
        return result.Data;
    }
}
