using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace AutoMidiPlayer.WPF.Services.OnlineMidi;

public record OnlineMidiDownloadResult(byte[] Data, string Title, System.Collections.Generic.Dictionary<int, string>? TrackNames = null);

public interface IOnlineMidiProvider
{
    string Id { get; }
    string DisplayName { get; }
    bool RequiresAccount { get; }
    bool SupportsTags { get; }

    IReadOnlyList<FilterOption> SortOptions { get; }
    IReadOnlyList<FilterOption> CategoryOptions { get; }

    Task<OnlineMidiPageResult> BrowseAsync(int page, string sortKey, string? categorySlug, bool forceRefresh, CancellationToken cancellationToken = default);
    Task<OnlineMidiPageResult> SearchAsync(string query, int page, string sortKey, bool forceRefresh, CancellationToken cancellationToken = default);
    
    Task<OnlineMidiDownloadResult> DownloadMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default);
    Task<byte[]> DownloadPreviewMidiAsync(OnlineMidiItem item, CancellationToken cancellationToken = default);
}
