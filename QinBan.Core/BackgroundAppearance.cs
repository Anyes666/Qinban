namespace QinBan.Core;

public enum WallpaperFit { Cover, Contain }
public sealed class AppearanceSettings
{
    public string PresetId { get; set; } = "night";
    public string? CustomRelativePath { get; set; }
    public string CustomName { get; set; } = "我的图片";
    public WallpaperFit Fit { get; set; } = WallpaperFit.Cover;
    public double Darkness { get; set; } = .32;
    public double Blur { get; set; }
    public double PanelOpacity { get; set; } = .84;
    public double FocusX { get; set; } = .68;
    public double FocusY { get; set; } = .5;
    public AppearanceSettings Copy() => (AppearanceSettings)MemberwiseClone();
    public void Validate()
    {
        if (PresetId is not ("night" or "blue" or "plain" or "custom")) throw new FormatException("未知背景选项。");
        if (!Enum.IsDefined(Fit)) throw new FormatException("不支持此背景缩放模式。");
        if (!double.IsFinite(Darkness) || Darkness is < .20 or > .82 || !double.IsFinite(Blur) || Blur is < 0 or > 18 ||
            !double.IsFinite(PanelOpacity) || PanelOpacity is < .78 or > .97 ||
            !double.IsFinite(FocusX) || FocusX is < 0 or > 1 || !double.IsFinite(FocusY) || FocusY is < 0 or > 1)
            throw new FormatException("背景参数超出安全显示范围。");
        if (CustomName == null || CustomName.Length > 200) throw new FormatException("背景名称过长。");
        if (PresetId == "custom" && string.IsNullOrWhiteSpace(CustomRelativePath)) throw new FormatException("自定义背景缺少本地图片路径。");
    }
}
public readonly record struct ImagePlacement(double X, double Y, double Width, double Height);
public static class BackgroundLayout
{
    // Deterministic aspect-preserving layout; focus applies only to the cropped axis.
    public static ImagePlacement Place(double imageWidth, double imageHeight, double width, double height,
        WallpaperFit fit, double focusX, double focusY)
    {
        if (new[] { imageWidth, imageHeight, width, height }.Any(v => !double.IsFinite(v) || v <= 0) ||
            !double.IsFinite(focusX) || !double.IsFinite(focusY) || !Enum.IsDefined(fit)) throw new ArgumentException("背景尺寸或缩放参数无效。");
        double scale = fit == WallpaperFit.Cover ? Math.Max(width / imageWidth, height / imageHeight) : Math.Min(width / imageWidth, height / imageHeight);
        double w = imageWidth * scale, h = imageHeight * scale;
        return fit == WallpaperFit.Contain ? new((width - w) / 2, (height - h) / 2, w, h) :
            new(Math.Clamp(width / 2 - w * Math.Clamp(focusX, 0, 1), Math.Min(0, width - w), 0),
                Math.Clamp(height / 2 - h * Math.Clamp(focusY, 0, 1), Math.Min(0, height - h), 0), w, h);
    }
    public static string ResolveCustom(string dataDirectory, string relative)
    {
        string root = Path.GetFullPath(Path.Combine(dataDirectory, "backgrounds"));
        string full = Path.GetFullPath(Path.Combine(dataDirectory, relative));
        string within = Path.GetRelativePath(root, full);
        if (Path.IsPathRooted(relative) || within.StartsWith("..") || Path.IsPathRooted(within) ||
            Path.GetDirectoryName(full) != root || !Path.GetExtension(full).Equals(".png", StringComparison.OrdinalIgnoreCase))
            throw new FormatException("背景图片路径越界；只读取本地 backgrounds 内的已导入 PNG。");
        return full;
    }
}
public readonly record struct UiRgb(byte R, byte G, byte B)
{
    public UiRgb Over(UiRgb background, double opacity) => new((byte)Math.Round(R * opacity + background.R * (1 - opacity)),
        (byte)Math.Round(G * opacity + background.G * (1 - opacity)), (byte)Math.Round(B * opacity + background.B * (1 - opacity)));
    public double Luminance
    {
        get { double Linear(byte v) { double x = v / 255.0; return x <= .04045 ? x / 12.92 : Math.Pow((x + .055) / 1.055, 2.4); } return .2126 * Linear(R) + .7152 * Linear(G) + .0722 * Linear(B); }
    }
    public double Contrast(UiRgb other) => (Math.Max(Luminance, other.Luminance) + .05) / (Math.Min(Luminance, other.Luminance) + .05);
}
