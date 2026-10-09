using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
namespace QinBan.Desktop;

internal static class BackgroundImageLoader
{
    public const long MaxBytes = 20 * 1024 * 1024;
    public const long MaxPixels = 40_000_000;
    public const int DecodeLimit = 1920;
    public static bool SupportedExtension(string path) => new[] { ".png", ".jpg", ".jpeg", ".bmp" }.Contains(Path.GetExtension(path).ToLowerInvariant());
    public static BitmapSource LoadFile(string path)
    {
        if (!SupportedExtension(path)) throw new FormatException("背景支持 PNG、JPG、JPEG 和 BMP；不接受 SVG、动图或程序文件。");
        var info = new FileInfo(path);
        if (!info.Exists) throw new FileNotFoundException("背景图片不存在；原文件未修改。", path);
        if (info.Length == 0 || info.Length > MaxBytes) throw new FormatException("背景图片须为 1 字节–20 MB。");
        int width, height, orientation = 1;
        using (var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            var decoder = BitmapDecoder.Create(stream, BitmapCreateOptions.DelayCreation, BitmapCacheOption.None);
            var frame = decoder.Frames[0]; width = frame.PixelWidth; height = frame.PixelHeight;
            if (width <= 0 || height <= 0 || width > 16000 || height > 16000 || (long)width * height > MaxPixels)
                throw new FormatException("背景图像过大：最长边不超过 16000 像素、总像素不超过 4000 万。");
            if (decoder is JpegBitmapDecoder && frame.Metadata is BitmapMetadata metadata && metadata.ContainsQuery("/app1/ifd/{ushort=274}"))
                orientation = Convert.ToInt32(metadata.GetQuery("/app1/ifd/{ushort=274}"));
        }
        BitmapSource source;
        using (var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
            // StreamSource has no URI cache key; OnLoad releases the original after decode.
            if (width >= height) image.DecodePixelWidth = Math.Min(DecodeLimit, width);
            else image.DecodePixelHeight = Math.Min(DecodeLimit, height);
            image.StreamSource = stream; image.EndInit(); image.Freeze(); source = image;
        }
        var transform = new TransformGroup();
        if (orientation is 2 or 5 or 7) transform.Children.Add(new ScaleTransform(-1, 1));
        if (orientation == 4) transform.Children.Add(new ScaleTransform(1, -1));
        int rotate = orientation switch { 3 => 180, 5 or 8 => 270, 6 or 7 => 90, _ => 0 };
        if (rotate != 0) transform.Children.Add(new RotateTransform(rotate));
        if (transform.Children.Count > 0) { var oriented = new TransformedBitmap(source, transform); oriented.Freeze(); source = oriented; }
        return source;
    }
    public static Color Accent(BitmapSource? source)
    {
        if (source == null) return Color.FromRgb(184, 208, 236);
        var image = new FormatConvertedBitmap(source, PixelFormats.Bgra32, null, 0);
        int stride = image.PixelWidth * 4; var pixels = new byte[stride * image.PixelHeight]; image.CopyPixels(pixels, stride, 0);
        double r = 0, g = 0, b = 0, weight = 0;
        for (int y = 0; y < image.PixelHeight; y += Math.Max(1, image.PixelHeight / 24))
            for (int x = 0; x < image.PixelWidth; x += Math.Max(1, image.PixelWidth / 24))
            {
                int at = y * stride + x * 4; double rr = pixels[at + 2] / 255.0, gg = pixels[at + 1] / 255.0, bb = pixels[at] / 255.0;
                double maximum = Math.Max(rr, Math.Max(gg, bb)), minimum = Math.Min(rr, Math.Min(gg, bb));
                double saturation = maximum == 0 ? 0 : (maximum - minimum) / maximum;
                if (maximum < .16 || saturation < .2 || pixels[at + 3] < 128) continue;
                double w = saturation * maximum; r += rr * w; g += gg * w; b += bb * w; weight += w;
            }
        if (weight == 0) return Color.FromRgb(184, 208, 236);
        double low = Math.Min(r, Math.Min(g, b)), high = Math.Max(r, Math.Max(g, b));
        if (high - low < weight * .03) return Color.FromRgb(184, 208, 236);
        // A light, hue-preserving tint keeps small accent text readable on every allowed panel.
        byte Tint(double channel) => (byte)Math.Clamp(Math.Round(184 + (channel - low) / (high - low) * 52), 184, 236);
        return Color.FromRgb(Tint(r), Tint(g), Tint(b));
    }
}
