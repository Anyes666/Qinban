using System.Diagnostics;
namespace QinBan.Core;

public interface IKeySink
{
    void Press(IReadOnlyList<char> keys);
    void Release(IReadOnlyList<char> keys);
    void ReleaseAll();
}
public sealed record InputGuard(bool Allowed, string Reason = "");
public sealed record PlaybackResult(string Reason, bool Completed, int NotesPressed);

// A managed scheduler with an injected output. Tests use a recorder, never the OS keyboard.
public sealed class PlaybackEngine
{
    private readonly object _gate = new();
    private readonly IKeySink _sink;
    private readonly Func<InputGuard> _guard;
    private CancellationTokenSource? _cancel;
    private bool _paused;
    private bool _stopped = true;
    private string _stopReason = "已停止";
    public bool IsRunning { get; private set; }
    public bool IsPaused { get { lock (_gate) return _paused; } }
    public double PositionMs { get; private set; }
    public PlaybackEngine(IKeySink sink, Func<InputGuard> guard) { _sink = sink; _guard = guard; }
    public void Stop(string reason = "手动停止")
    {
        lock (_gate)
        {
            _stopped = true; _stopReason = reason; _cancel?.Cancel();
            _sink.ReleaseAll();
        }
    }
    public void TogglePause()
    {
        lock (_gate)
        {
            if (!IsRunning || _stopped) return;
            if (!_paused) { _paused = true; _sink.ReleaseAll(); }
            else
            {
                var guard = _guard();
                if (!guard.Allowed) { Stop(guard.Reason); return; }
                _paused = false;
            }
        }
    }
    public async Task<PlaybackResult> PlayAsync(PlaybackPlan plan, PlayOptions options, double startMs = 0)
    {
        options.Validate();
        if (plan.Notes.Count == 0) throw new InvalidOperationException("没有可演奏音符。");
        CancellationToken token;
        lock (_gate)
        {
            if (IsRunning) throw new InvalidOperationException("已有演奏正在运行。");
            var guard = _guard(); if (!guard.Allowed) throw new InvalidOperationException(guard.Reason);
            _cancel = new(); token = _cancel.Token; IsRunning = true; _stopped = false; _paused = false;
        }
        int pressed = 0;
        double segmentStart = options.Loop ? options.LoopStartMs / options.Speed : Math.Clamp(startMs, 0, plan.DurationMs);
        double segmentEnd = options.Loop && options.LoopEndMs > 0 ? Math.Min(plan.DurationMs, options.LoopEndMs / options.Speed) : plan.DurationMs;
        if (segmentEnd <= segmentStart) Stop("循环或起始位置没有可演奏时长");
        try
        {
            do
            {
                var events = plan.Notes.Where(n => n.StartMs >= segmentStart && n.StartMs < segmentEnd)
                    .SelectMany(n => new[] { (At: n.StartMs, Down: true, n.Key), (At: Math.Min(segmentEnd, n.StartMs + n.HoldMs), Down: false, n.Key) })
                    .GroupBy(e => e.At).OrderBy(g => g.Key).ToList();
                int index = 0; double elapsed = 0;
                var watch = Stopwatch.StartNew(); double previous = watch.Elapsed.TotalMilliseconds;
                while (elapsed < segmentEnd - segmentStart || index < events.Count)
                {
                    token.ThrowIfCancellationRequested();
                    double now = watch.Elapsed.TotalMilliseconds, delta = now - previous; previous = now;
                    lock (_gate)
                    {
                        if (_stopped) token.ThrowIfCancellationRequested();
                        var guard = _guard();
                        if (!guard.Allowed) { Stop(guard.Reason); token.ThrowIfCancellationRequested(); }
                        if (!_paused)
                        {
                            elapsed += delta; PositionMs = Math.Min(segmentEnd, segmentStart + elapsed);
                            while (index < events.Count && events[index].Key <= PositionMs)
                            {
                                var ev = events[index++];
                                var ups = ev.Where(e => !e.Down).Select(e => e.Key).Distinct().ToArray();
                                var downs = ev.Where(e => e.Down).Select(e => e.Key).Distinct().ToArray();
                                if (ups.Length > 0) _sink.Release(ups);
                                if (downs.Length > 0) { _sink.Press(downs); pressed += downs.Length; }
                            }
                        }
                    }
                    await Task.Delay(3, token).ConfigureAwait(false);
                }
                lock (_gate) _sink.ReleaseAll();
                if (!options.Loop) break;
                await Task.Delay(100, token).ConfigureAwait(false);
            } while (!token.IsCancellationRequested);
            return new("演奏完成", true, pressed);
        }
        catch (OperationCanceledException) { return new(_stopReason, false, pressed); }
        catch (Exception ex) { return new("演奏中断：" + ex.Message, false, pressed); }
        finally
        {
            lock (_gate)
            {
                _stopped = true; IsRunning = false; _paused = false;
                _sink.ReleaseAll(); _cancel?.Dispose(); _cancel = null;
            }
        }
    }
}
