using System.Diagnostics;
namespace QinBan.Core;

public sealed record PreparedScore(SongDocument Song, PlaybackPlan Plan, IReadOnlyList<TrackInfo> Tracks,
    PlayOptions Options, int WorkerThreadId, double PreparationMs);

/// <summary>Only one bounded source parse/map runs per window; superseded requests cancel while waiting.</summary>
public sealed class ScorePreparer
{
    private readonly SemaphoreSlim _singleFlight = new(1, 1);
    public async Task<PreparedScore> PrepareAsync(Func<SongDocument> loadSource, PlayOptions options, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(loadSource); ArgumentNullException.ThrowIfNull(options);
        var snapshot = options.Copy(); snapshot.Validate(); cancellationToken.ThrowIfCancellationRequested();
        await _singleFlight.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await Task.Run(() =>
            {
                var watch = Stopwatch.StartNew(); cancellationToken.ThrowIfCancellationRequested();
                // File parsers have a 16 MiB / 100k-note budget. Parsing itself is not forcibly aborted.
                var song = loadSource(); cancellationToken.ThrowIfCancellationRequested();
                var plan = GameMapping.Build(song, snapshot, cancellationToken);
                var tracks = song.Tracks; cancellationToken.ThrowIfCancellationRequested();
                return new PreparedScore(song, plan, tracks, snapshot, Environment.CurrentManagedThreadId, watch.Elapsed.TotalMilliseconds);
            }, cancellationToken).ConfigureAwait(false);
        }
        finally { _singleFlight.Release(); }
    }
}
