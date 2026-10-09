using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using QinBan.Core;
namespace QinBan.Desktop;

// Only the wallpaper layer is blurred; labels and controls never receive a BlurEffect.
public sealed class WallpaperView : FrameworkElement
{
    public BitmapSource? Source { get; set; }
    public WallpaperFit Fit { get; set; } = WallpaperFit.Cover;
    public double FocusX { get; set; } = .68;
    public double FocusY { get; set; } = .5;
    internal ImagePlacement? LastPlacement { get; private set; }
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc); LastPlacement = null;
        if (Source == null || ActualWidth <= 0 || ActualHeight <= 0) return;
        var p = BackgroundLayout.Place(Source.PixelWidth, Source.PixelHeight, ActualWidth, ActualHeight, Fit, FocusX, FocusY);
        LastPlacement = p;
        dc.PushClip(new RectangleGeometry(new Rect(0, 0, ActualWidth, ActualHeight)));
        dc.DrawImage(Source, new Rect(p.X, p.Y, p.Width, p.Height)); dc.Pop();
    }
}
