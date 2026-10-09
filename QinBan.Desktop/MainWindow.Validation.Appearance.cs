using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    // All fixtures live under --ui-test's isolated output. Never send OS/game input.
    private async Task ValidateAppearanceAsync(string output, Func<string, Func<Task>, Task> test,
        Action<string, Action> sync, Action<bool, string> check)
    {
        string fixtures = Path.Combine(output, "背景验证"); Directory.CreateDirectory(fixtures);
        Width = 1460; Height = 940; UpdateLayout(); await Task.Delay(80);
        sync("Two embedded wallpapers decode; plain is an explicit no-image choice", () =>
        {
            check(BackgroundPresetList.Items.Count == 3, "wallpaper choices");
            foreach (var choice in WallpaperChoices.Where(c => c.File != null))
            {
                var image = new BitmapImage(choice.Thumbnail!);
                check(image.PixelWidth > 1000 && image.PixelWidth <= 1920, "embedded image " + choice.Id);
            }
            check(WallpaperLayer.Source != null && _appearance.PresetId == "night", "default wallpaper");
        });
        sync("Preset selection updates theme brushes and background across every page", () =>
        {
            BackgroundPresetList.SelectedIndex = 1;
            var source = WallpaperLayer.Source;
            check(_appearance.PresetId == "blue" && source != null && ReferenceEquals(source, AppearancePreviewImage.Source), "preset / preview");
            check(ReferenceEquals(LibraryPanel.Background, FindResource("PanelBrush")), "dynamic panel brush");
            check(((SolidColorBrush)PreviewButton.Background).Color == _themeAccent, "primary theme brush");
            foreach (var page in new[] { "library", "editor", "settings", "help", "appearance" })
            {
                SetPage(page); check(ReferenceEquals(source, WallpaperLayer.Source), "wallpaper missing on " + page);
                check(WallpaperLayer.ActualWidth == AppSurface.ActualWidth && WallpaperLayer.ActualHeight == AppSurface.ActualHeight, "wallpaper covers shell");
            }
        });
        SetPage("library"); UpdateLayout(); await Task.Delay(80); Capture(Path.Combine(output, "background-blue-1460.png"));
        SetPage("appearance"); UpdateLayout(); await Task.Delay(80); Capture(Path.Combine(output, "appearance-1460.png"));
        sync("All appearance controls fit without initial scrolling in the wide window", () =>
        {
            var bottom = FocusYSlider.TransformToAncestor(AppearancePage).Transform(new Point(0, FocusYSlider.ActualHeight));
            check(bottom.Y <= AppearancePage.ActualHeight - 2, "wide appearance form clipped");
        });
        sync("Plain mode removes only wallpaper and retains the music workbench", () =>
        {
            BackgroundPresetList.SelectedIndex = 2;
            check(WallpaperLayer.Source == null && _appearance.PresetId == "plain" && _plan!.Notes.Count > 0, "plain mode");
        });
        SetPage("library"); UpdateLayout(); Capture(Path.Combine(output, "background-plain-1460.png"));
        sync("Appearance sliders and fit control persist and reuse the cached bitmap", () =>
        {
            BackgroundPresetList.SelectedIndex = 1; var source = WallpaperLayer.Source;
            BackgroundFitCombo.SelectedIndex = 1; DarknessSlider.Value = .45; BlurSlider.Value = 5; PanelOpacitySlider.Value = .9;
            FocusXSlider.Value = .2; FocusYSlider.Value = .75;
            var prefs = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(_prefsPath), JsonDefaults.Options)!;
            check(prefs.Appearance?.Fit == WallpaperFit.Contain && prefs.Appearance.Blur == 5 && prefs.Appearance.FocusY == .75, "appearance persistence");
            check(ReferenceEquals(source, WallpaperLayer.Source) && WallpaperLayer.Effect is BlurEffect && Workbench.Effect == null && NowTitle.Effect == null, "blur only wallpaper / cache");
            check(QuickSpeedLabel.Text == SpeedLabel.Text, "quick speed label");
            BackgroundReset_Click(this, new());
        });
        sync("Old preferences without appearance load with compatible defaults", () =>
        {
            File.WriteAllText(_prefsPath, "{\"volume\":0.35,\"queueAuto\":false,\"instrumentId\":\"windsong\"}");
            _appearance.PresetId = "blue"; LoadPreferences(); LoadAppearanceControls(); ApplyAppearance();
            check(_appearance.PresetId == "night" && VolumeSlider.Value == .35 && SelectedInstrument.Id == "windsong", "old preference compatibility");
            SavePreferences();
        });
        string wide = Path.Combine(fixtures, "宽幅-原图.png"), white = Path.Combine(fixtures, "白色背景.png"), portrait = Path.Combine(fixtures, "竖图.png");
        WriteImageFixture(wide, 2560, 900, Color.FromRgb(40, 140, 210));
        WriteImageFixture(white, 600, 400, Colors.White); WriteImageFixture(portrait, 600, 1200, Color.FromRgb(190, 150, 80));
        string sourceHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(wide)));
        string? customCopy = null;
        await test("Local import normalizes to 1920, preserves original bytes and holds no source lock", async () =>
        {
            check(await ImportBackgroundAsync(wide), "local import: " + StatusText.Text);
            check(_appearance.PresetId == "custom" && _appearance.CustomName == "宽幅-原图.png", "custom name");
            customCopy = BackgroundLayout.ResolveCustom(_store.DataDirectory, _appearance.CustomRelativePath!);
            check(File.Exists(customCopy) && WallpaperLayer.Source!.PixelWidth == 1920 && WallpaperLayer.Source.PixelHeight == 675, "decode size");
            check(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(wide))) == sourceHash, "original modified");
            using var source = File.Open(wide, FileMode.Open, FileAccess.Read, FileShare.None);
            check(source.Length > 0, "source remains locked");
        });
        sync("Custom preference reload opens the normalized local copy independently of the source", () =>
        {
            var relative = _appearance.CustomRelativePath; _appearance = new(); _wallpaperCache.Clear();
            LoadPreferences(); LoadAppearanceControls(); ApplyAppearance();
            check(_appearance.CustomRelativePath == relative && WallpaperLayer.Source!.PixelWidth == 1920 && _backgroundProblem == null, "custom reload");
            var normalized = BitmapDecoder.Create(new Uri(customCopy!), BitmapCreateOptions.None, BitmapCacheOption.OnLoad).Frames[0];
            check(normalized.Metadata == null || normalized.Metadata is BitmapMetadata metadata && !metadata.ContainsQuery("/app1/ifd/{ushort=274}"), "normalized EXIF retained");
        });
        await test("EXIF rotation is honored and the input JPEG is read-only", async () =>
        {
            string jpeg = Path.Combine(fixtures, "旋转-EXIF.jpg"); WriteImageFixture(jpeg, 120, 80, Colors.CornflowerBlue, 6);
            var hash = SHA256.HashData(File.ReadAllBytes(jpeg)); var loaded = await Task.Run(() => BackgroundImageLoader.LoadFile(jpeg));
            check(loaded.PixelWidth == 80 && loaded.PixelHeight == 120 && loaded.IsFrozen, "EXIF orientation");
            check(await ImportBackgroundAsync(jpeg), "oriented import");
            check(WallpaperLayer.Source!.PixelWidth == 80 && WallpaperLayer.Source.PixelHeight == 120, "oriented copy");
            check(hash.SequenceEqual(SHA256.HashData(File.ReadAllBytes(jpeg))), "EXIF source changed");
        });
        await test("BMP images decode through the same bounded local importer", async () =>
        {
            string bmp = Path.Combine(fixtures, "背景.bmp"); WriteImageFixture(bmp, 120, 80, Colors.Teal);
            check(await ImportBackgroundAsync(bmp) && WallpaperLayer.Source!.PixelWidth == 120, "BMP import");
        });
        await test("Corrupt, empty, unsupported and over-limit files preserve the current background", async () =>
        {
            string corrupt = Path.Combine(fixtures, "损坏.png"), empty = Path.Combine(fixtures, "空图.jpg"), svg = Path.Combine(fixtures, "拒绝.svg"), large = Path.Combine(fixtures, "超限.jpg");
            File.WriteAllText(corrupt, "this is not an image"); File.WriteAllBytes(empty, []); File.WriteAllText(svg, "unsupported");
            using (var stream = File.Create(large)) stream.SetLength(BackgroundImageLoader.MaxBytes + 1);
            string old = JsonSerializer.Serialize(_appearance, JsonDefaults.Options);
            var oldSource = WallpaperLayer.Source;
            foreach (string path in new[] { corrupt, empty, svg, large })
            {
                check(!await ImportBackgroundAsync(path), "accepted invalid image " + path);
                check(JsonSerializer.Serialize(_appearance, JsonDefaults.Options) == old && ReferenceEquals(oldSource, WallpaperLayer.Source), "changed on failed import");
                check(StatusText.Text.Contains("失败") && UploadBackgroundButton.IsEnabled, "failed import not reported");
            }
            Capture(Path.Combine(output, "appearance-import-error.png"));
        });
        sync("Missing custom file falls back without overwriting its saved path or score data", () =>
        {
            var original = _appearance.Copy(); string score = SongParser.ToJson(_song!);
            _appearance.PresetId = "custom"; _appearance.CustomRelativePath = "backgrounds/missing.png";
            ApplyAppearance(); SavePreferences();
            check(_backgroundProblem != null && WallpaperLayer.Source != null && _appearance.CustomRelativePath == "backgrounds/missing.png", "missing background fallback");
            check(SongParser.ToJson(_song!) == score && File.ReadAllText(_prefsPath).Contains("missing.png"), "fallback rewrote data");
            Capture(Path.Combine(output, "appearance-missing-fallback.png"));
            _appearance = original; LoadAppearanceControls(); ApplyAppearance(); SavePreferences();
        });
        sync("Out-of-directory custom paths are refused without reading arbitrary files", () =>
        {
            var original = _appearance.Copy();
            _appearance.CustomRelativePath = "../outside.png"; ApplyAppearance();
            check(_backgroundProblem != null && _appearance.CustomRelativePath == "../outside.png", "path escape");
            _appearance = original; LoadAppearanceControls(); ApplyAppearance(); SavePreferences();
        });
        await test("Portrait cover and contain keep aspect ratio and focal controls work", async () =>
        {
            check(await ImportBackgroundAsync(portrait), "portrait import");
            SetPage("library"); UpdateLayout(); Capture(Path.Combine(output, "background-portrait-cover.png"));
            var cover = WallpaperLayer.LastPlacement!.Value;
            check(Math.Abs(cover.Width / cover.Height - .5) < .001 && cover.Width >= AppSurface.ActualWidth - .01 && cover.Height >= AppSurface.ActualHeight - .01, "portrait cover");
            FocusYSlider.Value = 0; Capture(Path.Combine(output, "background-portrait-focus-top.png"));
            check(Math.Abs(WallpaperLayer.LastPlacement!.Value.Y) < .01, "focus top");
            FocusYSlider.Value = 1; Capture(Path.Combine(output, "background-portrait-focus-bottom.png"));
            check(Math.Abs(WallpaperLayer.LastPlacement!.Value.Y + cover.Height - AppSurface.ActualHeight) < .01, "focus bottom");
            BackgroundFitCombo.SelectedIndex = 1; UpdateLayout(); Capture(Path.Combine(output, "background-portrait-contain.png"));
            var contain = WallpaperLayer.LastPlacement!.Value;
            check(contain.Width <= AppSurface.ActualWidth + .01 && contain.Height <= AppSurface.ActualHeight + .01 && contain.X >= 0 && contain.Y >= 0, "portrait contain");
        });
        await test("Bright-white wallpaper keeps panels, selection and primary text readable", async () =>
        {
            check(await ImportBackgroundAsync(white), "white import");
            BackgroundFitCombo.SelectedIndex = 0; DarknessSlider.Value = .2; PanelOpacitySlider.Value = .78; BlurSlider.Value = 0;
            SetPage("library"); UpdateLayout(); Capture(Path.Combine(output, "background-white-minimum.png"));
            static UiRgb Rgb(Color color) => new(color.R, color.G, color.B);
            var bright = Rgb(((SolidColorBrush)WallpaperMask.Background).Color).Over(new(255, 255, 255), WallpaperMask.Opacity);
            Color panelBrush = ((SolidColorBrush)LibraryPanel.Background).Color;
            var panel = Rgb(panelBrush).Over(bright, panelBrush.A / 255d);
            var muted = Rgb(((SolidColorBrush)FindResource("MutedBrush")).Color);
            var selected = Rgb(((SolidColorBrush)FindResource("SelectedRowBrush")).Color);
            check(muted.Contrast(panel) >= 4.5 && muted.Contrast(selected) >= 4.5 && Rgb(_themeAccent).Contrast(panel) >= 4.5, "small text / selection contrast");
            check(Rgb(((SolidColorBrush)PreviewButton.Foreground).Color).Contrast(Rgb(_themeAccent)) >= 4.5, "primary text contrast");
            check(Workbench.Effect == null && NowTitle.Effect == null && Roll.Effect == null, "blur applied to content");
        });
        sync("Long Chinese title stays inside the card and preserves the source score", () =>
        {
            string oldTitle = NowTitle.Text, oldAuthor = NowAuthor.Text, score = SongParser.ToJson(_song!);
            try
            {
                NowTitle.Text = string.Concat(Enumerable.Repeat("一首很长的中文歌曲名称", 20));
                NowAuthor.Text = string.Concat(Enumerable.Repeat("作者与来源说明", 30)); UpdateLayout();
                check(NowTitle.ActualWidth < WorkbenchScroll.ActualWidth && NowTitle.TextTrimming == TextTrimming.CharacterEllipsis, "title overflow");
                CheckFooterBounds(); Capture(Path.Combine(output, "long-title-white.png"));
                check(SongParser.ToJson(_song!) == score, "source title changed");
            }
            finally { NowTitle.Text = oldTitle; NowAuthor.Text = oldAuthor; }
        });
        sync("Drawer keeps advanced controls available and Escape closes through the real routed handler", () =>
        {
            SetPage("library"); check(ParameterOverlay.Visibility == Visibility.Collapsed, "drawer initially open");
            ParametersToggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); UpdateLayout();
            check(ParameterOverlay.Visibility == Visibility.Visible && SpeedSlider.IsVisible && ChordCombo.IsVisible, "drawer controls hidden");
            check(KeyboardNavigation.GetTabNavigation(ParameterOverlay) == KeyboardNavigationMode.Cycle, "drawer tab scope");
            check(ParametersToggle.FocusVisualStyle != null && SpeedSlider.FocusVisualStyle != null && System.Windows.Automation.AutomationProperties.GetName(BackgroundFitCombo).Length > 0, "focus / accessible control name");
            Capture(Path.Combine(output, "parameters-drawer-white.png"));
            var source = PresentationSource.FromVisual(this)!;
            RaiseEvent(new KeyEventArgs(Keyboard.PrimaryDevice, source, 0, Key.Escape) { RoutedEvent = Keyboard.PreviewKeyDownEvent });
            check(ParameterOverlay.Visibility == Visibility.Collapsed && ParametersToggle.Content.ToString() == "演奏调校" && ReferenceEquals(FocusManager.GetFocusedElement(this), ParametersToggle), "Escape did not close drawer / restore logical focus");
        });
        Width = 1080; Height = 720; SetPage("appearance"); UpdateLayout(); await Task.Delay(80);
        Capture(Path.Combine(output, "appearance-1080.png"));
        sync("Narrow appearance page keeps image choice, upload and persistent controls reachable", () =>
        {
            CheckFooterBounds();
            var point = UploadBackgroundButton.TransformToAncestor(AppSurface).Transform(new Point());
            check(UploadBackgroundButton.IsVisible && point.X >= 0 && point.X + UploadBackgroundButton.ActualWidth <= AppSurface.ActualWidth, "upload out of bounds");
            AppearancePage.ScrollToEnd(); UpdateLayout();
            var focus = FocusYSlider.TransformToAncestor(AppearancePage).Transform(new Point());
            check(focus.Y >= 0 && focus.Y + FocusYSlider.ActualHeight <= AppearancePage.ActualHeight + 1, "appearance scroll inaccessible");
            AppearancePage.ScrollToTop();
        });
        await test("Background changes and local import do not interrupt muted preview or pending shortcut", async () =>
        {
            SetPage("library"); VolumeSlider.Value = 0; await StartPreviewAsync();
            for (int i = 0; i < 100 && !_previewActive; i++) await Task.Delay(40);
            check(_previewActive, "preview did not open"); var plan = _previewPlan; var selected = _selected;
            _launchGate.Request(new(true, true, true, true, false, true, true));
            BackgroundPresetList.SelectedIndex = 1; DarknessSlider.Value = .5;
            check(await ImportBackgroundAsync(wide), "import during preview");
            check(_previewActive && ReferenceEquals(plan, _previewPlan) && ReferenceEquals(selected, _selected) && _launchGate.Pending && _nativeAttempts == 0, "appearance interrupted music / shortcut");
            EmergencyStop("外观自测试听结束");
        });
        sync("Restore defaults never deletes previously imported backgrounds", () =>
        {
            string root = Path.Combine(_store.DataDirectory, "backgrounds"); var before = Directory.GetFiles(root).Order().ToArray();
            BackgroundResetButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            check(_appearance.PresetId == "night" && _appearance.Darkness == .32 && WallpaperLayer.Source != null, "reset default");
            check(before.SequenceEqual(Directory.GetFiles(root).Order()) && File.Exists(customCopy), "reset deleted local data");
        });
        Width = 1460; Height = 940; SetPage("library"); UpdateLayout(); await Task.Delay(80);
        ParametersToggle_Click(this, new()); UpdateLayout(); Capture(Path.Combine(output, "parameters-drawer.png")); ParametersClose_Click(this, new());
    }
    private static void WriteImageFixture(string path, int width, int height, Color color, ushort? orientation = null)
    {
        byte[] pixels = new byte[width * height * 4];
        for (int at = 0; at < pixels.Length; at += 4) { pixels[at] = color.B; pixels[at + 1] = color.G; pixels[at + 2] = color.R; pixels[at + 3] = 255; }
        var image = BitmapSource.Create(width, height, 96, 96, PixelFormats.Bgra32, null, pixels, width * 4); image.Freeze();
        BitmapEncoder encoder = Path.GetExtension(path) switch { ".jpg" => new JpegBitmapEncoder(), ".bmp" => new BmpBitmapEncoder(), _ => new PngBitmapEncoder() };
        BitmapMetadata? metadata = null;
        if (orientation.HasValue) { metadata = new BitmapMetadata("jpg"); metadata.SetQuery("/app1/ifd/{ushort=274}", orientation.Value); }
        encoder.Frames.Add(BitmapFrame.Create(image, null, metadata, null));
        using var stream = File.Create(path); encoder.Save(stream);
    }
}
