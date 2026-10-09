using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private AppearanceSettings _appearance = new();
    private bool _loadingAppearance, _importingBackground;
    private BitmapSource? _accentSource;
    private readonly Dictionary<string, BitmapSource> _wallpaperCache = [];
    private string? _backgroundProblem;
    private Color _themeAccent;
    private sealed record WallpaperChoice(string Id, string Name, string Detail, string? File)
    {
        public Uri? Thumbnail => File == null ? null : new Uri("pack://application:,,,/Assets/Backgrounds/" + File);
    }
    private static readonly WallpaperChoice[] WallpaperChoices =
    [
        new("night", "星夜", "深蓝 · 留白 · 宁静", "night.jpg"),
        new("blue", "霓蓝", "青蓝 · 明亮 · 通透", "blue.jpg"),
        new("plain", "纯净深色", "无图片 · 专注演奏", null)
    ];
    private void InitializeAppearance()
    {
        _loadingAppearance = true;
        BackgroundPresetList.ItemsSource = WallpaperChoices;
        _loadingAppearance = false;
        LoadAppearanceControls(); ApplyAppearance();
    }
    private void LoadAppearanceControls()
    {
        _loadingAppearance = true;
        BackgroundPresetList.SelectedItem = WallpaperChoices.FirstOrDefault(w => w.Id == _appearance.PresetId);
        BackgroundFitCombo.SelectedIndex = (int)_appearance.Fit;
        DarknessSlider.Value = _appearance.Darkness; BlurSlider.Value = _appearance.Blur; PanelOpacitySlider.Value = _appearance.PanelOpacity;
        FocusXSlider.Value = _appearance.FocusX; FocusYSlider.Value = _appearance.FocusY;
        _loadingAppearance = false;
    }
    private BitmapSource? WallpaperSource()
    {
        if (_appearance.PresetId == "plain") return null;
        string key;
        if (_appearance.PresetId == "custom") key = BackgroundLayout.ResolveCustom(_store.DataDirectory, _appearance.CustomRelativePath!);
        else key = "pack://application:,,,/Assets/Backgrounds/" + WallpaperChoices.Single(w => w.Id == _appearance.PresetId).File;
        if (_wallpaperCache.TryGetValue(key, out var cached)) return cached;
        BitmapSource image;
        if (_appearance.PresetId == "custom") image = BackgroundImageLoader.LoadFile(key);
        else { var bitmap = new BitmapImage(new Uri(key)); bitmap.Freeze(); image = bitmap; }
        _wallpaperCache[key] = image; return image;
    }
    private void ApplyAppearance()
    {
        _appearance.Validate(); BitmapSource? image;
        _backgroundProblem = null;
        try { image = WallpaperSource(); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or FormatException or NotSupportedException or ArgumentException)
        {
            // Cosmetic failure must not destroy a score library or rewrite the selected file path.
            _backgroundProblem = "自定义背景加载失败，暂用星夜；原配置及文件保留。" + ex.Message;
            var fallback = new BitmapImage(new Uri("pack://application:,,,/Assets/Backgrounds/night.jpg")); fallback.Freeze(); image = fallback;
        }
        foreach (var view in new[] { WallpaperLayer, AppearancePreviewImage })
        {
            view.Source = image; view.Fit = _appearance.Fit; view.FocusX = _appearance.FocusX; view.FocusY = _appearance.FocusY;
            view.Effect = _appearance.Blur > 0 ? new BlurEffect { Radius = _appearance.Blur, RenderingBias = RenderingBias.Performance } : null;
            view.InvalidateVisual();
        }
        WallpaperMask.Opacity = PreviewWallpaperMask.Opacity = _appearance.Darkness;
        if (!ReferenceEquals(_accentSource, image) || _themeAccent == default)
        { _themeAccent = BackgroundImageLoader.Accent(image); _accentSource = image; }
        Roll.Accent = new SolidColorBrush(_themeAccent); Roll.InvalidateVisual();
        Resources["AccentBrush"] = new SolidColorBrush(_themeAccent);
        Resources["PanelBrush"] = new SolidColorBrush(Color.FromArgb((byte)Math.Round(_appearance.PanelOpacity * 255), 19, 28, 43));
        Resources["RaisedBrush"] = new SolidColorBrush(Color.FromRgb(30, 43, 62));
        Resources["NavSelectedBrush"] = new SolidColorBrush(Color.FromArgb(65, _themeAccent.R, _themeAccent.G, _themeAccent.B));
        Resources["SelectedRowBrush"] = new SolidColorBrush(Color.FromRgb((byte)(_themeAccent.R * .18 + 13), (byte)(_themeAccent.G * .18 + 18), (byte)(_themeAccent.B * .18 + 28)));
        _activeKey = new SolidColorBrush(Color.FromRgb((byte)(_themeAccent.R * .45), (byte)(_themeAccent.G * .45), (byte)(_themeAccent.B * .45)));
        BackgroundNameText.Text = _backgroundProblem ?? (_appearance.PresetId == "custom" ? "当前：" + _appearance.CustomName + " · 本地副本" : "当前：" + WallpaperChoices.Single(w => w.Id == _appearance.PresetId).Name);
        DarknessValue.Text = $"{_appearance.Darkness:P0}"; BlurValue.Text = $"{_appearance.Blur:0} px";
        PanelOpacityValue.Text = $"{_appearance.PanelOpacity:P0}"; FocusXValue.Text = $"{_appearance.FocusX:P0}"; FocusYValue.Text = $"{_appearance.FocusY:P0}";
        PreviewBackgroundTitle.Text = _appearance.PresetId == "custom" ? _appearance.CustomName : WallpaperChoices.FirstOrDefault(w => w.Id == _appearance.PresetId)?.Name ?? "星夜";
        if (_ready) { RefreshNavigationAppearance(); if (_backgroundProblem != null) Status(_backgroundProblem); }
    }
    private void AppearancePreset_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_ready || _loadingAppearance || BackgroundPresetList.SelectedItem is not WallpaperChoice choice) return;
        _appearance.PresetId = choice.Id; _appearance.Darkness = choice.Id == "blue" ? .38 : .32;
        _appearance.FocusX = .68; _appearance.FocusY = .5; LoadAppearanceControls(); UpdateAppearance();
    }
    private void Appearance_Changed(object sender, RoutedPropertyChangedEventArgs<double> e) => ReadAppearanceControls();
    private void AppearanceFit_Changed(object sender, SelectionChangedEventArgs e) => ReadAppearanceControls();
    private void ReadAppearanceControls()
    {
        if (!_ready || _loadingAppearance) return;
        _appearance.Fit = (WallpaperFit)Math.Max(0, BackgroundFitCombo.SelectedIndex);
        _appearance.Darkness = DarknessSlider.Value; _appearance.Blur = BlurSlider.Value; _appearance.PanelOpacity = PanelOpacitySlider.Value;
        _appearance.FocusX = FocusXSlider.Value; _appearance.FocusY = FocusYSlider.Value; UpdateAppearance();
    }
    private bool UpdateAppearance()
    {
        try { ApplyAppearance(); SavePreferences(); return true; }
        catch (Exception ex) { ReportError(ex, "外观设置未保存（保留原偏好文件）"); return false; }
    }
    private async void BackgroundUpload_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "选择本地背景（不会上传）", Filter = "背景图片|*.png;*.jpg;*.jpeg;*.bmp", Multiselect = false };
        if (dialog.ShowDialog(this) == true) await ImportBackgroundAsync(dialog.FileName);
    }
    private async Task<bool> ImportBackgroundAsync(string source)
    {
        if (_importingBackground) { Status("图片仍在导入，请稍等。"); return false; }
        _importingBackground = true; UploadBackgroundButton.IsEnabled = false;
        Status("正在读取本地图片…不会上传或修改原图");
        var previous = _appearance.Copy();
        try
        {
            var image = await Task.Run(() => BackgroundImageLoader.LoadFile(source));
            string relative = Path.Combine("backgrounds", Guid.NewGuid().ToString("N") + ".png");
            string target = BackgroundLayout.ResolveCustom(_store.DataDirectory, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            // Pixel-only PNG removes imported EXIF/location metadata. The user's original is read-only.
            using (var stream = File.Open(target, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image)); encoder.Save(stream);
            }
            _wallpaperCache.Clear(); // Bounded memory; no files or original images are deleted.
            _wallpaperCache[target] = image;
            _appearance.PresetId = "custom"; _appearance.CustomRelativePath = relative;
            _appearance.CustomName = Path.GetFileName(source)[..Math.Min(180, Path.GetFileName(source).Length)];
            _appearance.FocusX = _appearance.FocusY = .5; LoadAppearanceControls();
            if (!UpdateAppearance())
            {
                _appearance = previous; LoadAppearanceControls(); ApplyAppearance();
                Status("背景偏好未保存；保留原设置及已生成副本。"); return false;
            }
            SetPage("appearance"); Status("已应用本地背景 · 原图未修改，不上传；副本随窗口等比适配"); return true;
        }
        catch (Exception ex) { _appearance = previous; LoadAppearanceControls(); ApplyAppearance(); ReportError(ex, "背景导入失败（保留原设置）"); return false; }
        finally { _importingBackground = false; UploadBackgroundButton.IsEnabled = true; }
    }
    private async void Background_Drop(object sender, DragEventArgs e)
    {
        e.Handled = true;
        if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
        var paths = (string[])e.Data.GetData(DataFormats.FileDrop);
        if (paths.Length != 1) { Status("每次请选择一张本地背景图片。"); return; }
        await ImportBackgroundAsync(paths[0]);
    }
    private void BackgroundReset_Click(object sender, RoutedEventArgs e)
    {
        _appearance = new(); LoadAppearanceControls(); if (UpdateAppearance()) Status("已恢复星夜默认外观；已导入图片副本没有删除。");
    }
    private void AppearanceNav_Click(object sender, RoutedEventArgs e) => SetPage("appearance");
    private void ParametersToggle_Click(object sender, RoutedEventArgs e)
    {
        bool open = ParameterOverlay.Visibility != Visibility.Visible;
        ParameterOverlay.Visibility = open ? Visibility.Visible : Visibility.Collapsed;
        ParametersToggle.Content = open ? "收起调校" : "演奏调校";
        if (open) { FocusManager.SetFocusedElement(this, SpeedSlider); SpeedSlider.Focus(); }
        else { FocusManager.SetFocusedElement(this, ParametersToggle); ParametersToggle.Focus(); }
    }
    private void ParametersClose_Click(object sender, RoutedEventArgs e)
    {
        ParameterOverlay.Visibility = Visibility.Collapsed; ParametersToggle.Content = "演奏调校"; FocusManager.SetFocusedElement(this, ParametersToggle); ParametersToggle.Focus();
    }
    private void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape && ParameterOverlay.Visibility == Visibility.Visible) { ParametersClose_Click(this, new()); e.Handled = true; }
    }
    private void AppearancePreview_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        var surface = (FrameworkElement)sender;
        surface.Clip = new RectangleGeometry(new Rect(0, 0, surface.ActualWidth, surface.ActualHeight), 16, 16);
    }
    private void Window_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (LibraryColumn != null) LibraryColumn.Width = new GridLength(ActualWidth < 1250 ? 236 : 264);
        if (NowTitle != null) NowTitle.FontSize = ActualWidth < 1250 ? 26 : 32;
    }
    private void RefreshNavigationAppearance()
    {
        foreach (var nav in new[] { NavLibrary, NavFavorites, NavQueue, NavEditor, NavAppearance, NavSettings, NavHelp })
        {
            bool active = (string)nav.Tag == _page;
            nav.Background = active ? (Brush)FindResource("NavSelectedBrush") : Brushes.Transparent;
            nav.Foreground = (Brush)FindResource(active ? "TextBrush" : "MutedBrush");
        }
    }
}
