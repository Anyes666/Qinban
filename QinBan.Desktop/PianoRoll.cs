using System.Globalization;
using System.Windows;
using System.Windows.Media;
using QinBan.Core;
namespace QinBan.Desktop;
public sealed class PianoRoll : FrameworkElement
{
    public InstrumentProfile Instrument { get; set; } = InstrumentCatalog.Get("windsong");
    public PlaybackPlan? Plan { get; set; }
    public double PositionMs { get; set; }
    public double WindowSeconds { get; set; } = 20;
    internal int DrawnNoteRectangles { get; private set; }
    internal IReadOnlyList<Rect> TimeLabelBounds { get; private set; } = [];
    private static readonly Brush Line = new SolidColorBrush(Color.FromRgb(42, 60, 74));
    private static readonly Brush Muted = new SolidColorBrush(Color.FromRgb(185, 198, 217));
    public Brush Accent { get; set; } = new SolidColorBrush(Color.FromRgb(149, 190, 230));
    private static readonly Brush Bass = new SolidColorBrush(Color.FromRgb(233, 203, 164));
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        double left = 43, top = 25, width = Math.Max(1, ActualWidth - left - 12), height = Math.Max(1, ActualHeight - top - 15);
        double duration = Plan?.DurationMs ?? 20000, span = WindowSeconds <= 0 ? Math.Max(1000, duration) : WindowSeconds * 1000;
        double start = Math.Floor(PositionMs / span) * span;
        if (PositionMs >= duration) start = Math.Max(0, Math.Ceiling(duration / span - 1) * span);
        var rows = Instrument.Keys.Where(k => k.IsChord).Concat(Instrument.MelodyKeys.OrderByDescending(k => k.Pitches[0])).ToArray();
        double row = height / Math.Max(1, rows.Length);
        var pen = new Pen(Line, .7);
        for (int i = 0; i < rows.Length; i++)
        {
            dc.DrawLine(pen, new(left, top + i * row), new(left + width, top + i * row));
            if (i % 7 == 0) Text(dc, rows[i].IsChord ? "和弦" : rows[i].Label, 0, top + i * row - 3, 11);
        }
        int divisions = 4;
        var ticks = new List<(double X, FormattedText Label, Rect Bounds)>();
        while (true)
        {
            ticks.Clear();
            for (int i = 0; i <= divisions; i++)
            {
                double x = left + width * i / divisions;
                var label = Format(string.Format(CultureInfo.InvariantCulture, "{0:0.#}s", (start + span * i / divisions) / 1000), 11);
                double labelX = i == divisions ? x - label.Width : x;
                ticks.Add((x, label, new Rect(labelX, 1, label.Width, label.Height)));
            }
            bool fits = ticks.All(t => t.Bounds.Left >= left && t.Bounds.Right <= left + width + .01)
                && ticks.Zip(ticks.Skip(1), (a, b) => b.Bounds.Left - a.Bounds.Right >= 8).All(gap => gap);
            if (fits || divisions == 1) break;
            divisions /= 2;
        }
        foreach (var tick in ticks)
        {
            dc.DrawLine(pen, new(tick.X, top), new(tick.X, top + height));
            dc.DrawText(tick.Label, tick.Bounds.TopLeft);
        }
        TimeLabelBounds = ticks.Select(t => t.Bounds).ToArray();
        // Very dense onsets already overlap at the minimum 3-DIP note width. Draw their
        // same-row/same-colour union instead of thousands of overlapping WPF geometries.
        // This only coalesces the visualization; all source and playback events remain intact.
        var keyRows = rows.Select((key, index) => (key.Key, index)).ToDictionary(item => item.Key, item => item.index);
        var rectangles = new Dictionary<(int Row, bool Bass), List<Rect>>();
        if (Plan != null)
            foreach (var note in Plan.Notes.Where(n => n.StartMs < start + span && n.StartMs + n.SoundMs > start).Take(5000))
            {
                if (!keyRows.TryGetValue(note.Key, out int keyIndex)) continue;
                double x = left + Math.Max(0, note.StartMs - start) / span * width;
                double end = Math.Min(start + span, note.StartMs + note.SoundMs);
                double w = Math.Min(Math.Max(3, (end - Math.Max(start, note.StartMs)) / span * width), left + width - x);
                var rectangle = new Rect(x, top + keyIndex * row + 2, w, Math.Max(3, row - 3));
                var groupKey = (keyIndex, note.Track != 0);
                if (!rectangles.TryGetValue(groupKey, out var group)) rectangles[groupKey] = group = [];
                if (group.Count > 0 && rectangle.Left <= group[^1].Right)
                {
                    var previous = group[^1];
                    group[^1] = new Rect(previous.Left, previous.Top, Math.Max(previous.Right, rectangle.Right) - previous.Left, previous.Height);
                }
                else group.Add(rectangle);
            }
        DrawnNoteRectangles = rectangles.Values.Sum(group => group.Count);
        foreach (var (key, group) in rectangles)
            foreach (var rectangle in group)
                dc.DrawRoundedRectangle(key.Bass ? Bass : Accent, null, rectangle, 2, 2);
        double cursor = left + Math.Clamp((PositionMs - start) / span, 0, 1) * width;
        dc.DrawLine(new Pen(Brushes.White, 1.3), new(cursor, top - 4), new(cursor, top + height));
    }
    private void Text(DrawingContext dc, string text, double x, double y, int size)
    {
        dc.DrawText(Format(text, size), new(x, y));
    }
    private FormattedText Format(string text, int size) => new(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight, new Typeface("Segoe UI"), size, Muted, VisualTreeHelper.GetDpi(this).PixelsPerDip);
}
