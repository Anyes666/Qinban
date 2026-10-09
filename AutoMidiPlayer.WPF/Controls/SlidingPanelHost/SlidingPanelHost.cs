using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace AutoMidiPlayer.WPF.Controls;

/// <summary>
/// Displays one child panel at a time and animates smooth horizontal slide
/// transitions between them. Add children directly in XAML; each child becomes
/// a "page" that can be navigated to.
///
/// <para><b>Usage:</b></para>
/// <code>
/// &lt;controls:SlidingPanelHost x:Name="Slider"&gt;
///     &lt;StackPanel&gt;  …panel 0…  &lt;/StackPanel&gt;
///     &lt;Grid&gt;        …panel 1…  &lt;/Grid&gt;
///     &lt;StackPanel&gt;  …panel 2…  &lt;/StackPanel&gt;
/// &lt;/controls:SlidingPanelHost&gt;
/// </code>
/// <code>
/// Slider.NavigateTo(2);   // slide left to panel 2
/// Slider.Reset();         // jump to panel 0 instantly
/// </code>
/// </summary>
public class SlidingPanelHost : Panel
{
    private int _activeIndex;
    private bool _isAnimating;
    private bool _initialised;

    // ── Animation defaults ──────────────────────────────────────────
    // QuinticEase-Out: fast start, smooth landing – feels responsive.
    private static readonly IEasingFunction SlideEase =
        new QuinticEase { EasingMode = EasingMode.EaseOut };

    private static readonly IEasingFunction HeightEase =
        new CubicEase { EasingMode = EasingMode.EaseOut };

    public SlidingPanelHost()
    {
        ClipToBounds = true;
        UseLayoutRounding = true;
        Loaded += OnLoaded;
    }

    /// <summary>Index of the currently visible panel.</summary>
    public int ActiveIndex => _activeIndex;

    /// <summary>Whether a slide animation is currently running.</summary>
    public bool IsAnimating => _isAnimating;

    /// <summary>Raised when a slide transition completes.</summary>
    public event EventHandler<int>? PanelChanged;

    // ── Dependency properties ───────────────────────────────────────

    #region Dependency Properties

    public static readonly DependencyProperty SlideDurationMsProperty =
        DependencyProperty.Register(nameof(SlideDurationMs), typeof(double),
            typeof(SlidingPanelHost), new PropertyMetadata(220.0));

    /// <summary>Slide animation duration in milliseconds (default 220).</summary>
    public double SlideDurationMs
    {
        get => (double)GetValue(SlideDurationMsProperty);
        set => SetValue(SlideDurationMsProperty, value);
    }

    public static readonly DependencyProperty ContentResizeDurationMsProperty =
        DependencyProperty.Register(nameof(ContentResizeDurationMs), typeof(double),
            typeof(SlidingPanelHost), new PropertyMetadata(180.0));

    /// <summary>
    /// Duration for the height animation when the active panel's content
    /// resizes (e.g. a section expands or collapses). Default 180 ms.
    /// </summary>
    public double ContentResizeDurationMs
    {
        get => (double)GetValue(ContentResizeDurationMsProperty);
        set => SetValue(ContentResizeDurationMsProperty, value);
    }

    #endregion

    // ── Layout ──────────────────────────────────────────────────────

    #region Layout

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_initialised) return;
        _initialised = true;

        for (int i = 0; i < InternalChildren.Count; i++)
        {
            var child = InternalChildren[i];
            EnsureTransform(child);
            child.Visibility = i == 0 ? Visibility.Visible : Visibility.Collapsed;
        }

        // Watch every child for content-size changes so height can animate.
        foreach (UIElement child in InternalChildren)
        {
            if (child is FrameworkElement fe)
                fe.SizeChanged += OnChildSizeChanged;
        }
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        var result = new Size();
        for (int i = 0; i < InternalChildren.Count; i++)
        {
            var child = InternalChildren[i];
            if (child.Visibility == Visibility.Collapsed) continue;

            child.Measure(availableSize);
            if (i == _activeIndex)
                result = child.DesiredSize;
        }
        return result;
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        foreach (UIElement child in InternalChildren)
        {
            if (child.Visibility == Visibility.Collapsed) continue;
            EnsureTransform(child);
            // Arrange child at Top with its actual DesiredSize, so it doesn't stretch 
            // and trigger another SizeChanged loop when the host animates its Height.
            var rect = new Rect(0, 0, finalSize.Width, child.DesiredSize.Height);
            child.Arrange(rect);
        }
        return finalSize;
    }

    #endregion

    // ── Content-resize animation ────────────────────────────────────

    private void OnChildSizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (_isAnimating || sender is not FrameworkElement fe) return;

        int idx = InternalChildren.IndexOf(fe);
        if (idx != _activeIndex) return;

        double oldHeight = e.PreviousSize.Height;
        double newHeight = e.NewSize.Height;

        // Skip the very first layout pass (oldHeight == 0) so we don't conflict with the popup's intro animation.
        if (oldHeight == 0 || newHeight < 1 || Math.Abs(oldHeight - newHeight) < 2) return;

        // Force the host back to the old height momentarily, then animate to the new height.
        Height = oldHeight;

        var anim = MakeAnim(newHeight,
            TimeSpan.FromMilliseconds(ContentResizeDurationMs), HeightEase);
        anim.Completed += (_, _) => ClearHeightLock();
        BeginAnimation(HeightProperty, anim);
    }

    // ── Public API ──────────────────────────────────────────────────

    #region Public API

    /// <summary>
    /// Slide to the child at <paramref name="index"/>.
    /// Higher index → slides left (forward); lower → slides right (backward).
    /// </summary>
    public void NavigateTo(int index)
    {
        if (index < 0 || index >= InternalChildren.Count) return;
        if (index == _activeIndex || _isAnimating) return;

        var current = InternalChildren[_activeIndex];
        var target = InternalChildren[index];
        bool forward = index > _activeIndex;

        double w = ActualWidth;
        if (w <= 0) w = 360;

        var dur = TimeSpan.FromMilliseconds(SlideDurationMs);
        _isAnimating = true;

        // 1 ─ Freeze container height at current value.
        double curH = ActualHeight;
        BeginAnimation(HeightProperty, null);
        Height = curH;

        // 2 ─ Position target off-screen, then make it visible.
        var txTarget = GetTransform(target);
        var txCurrent = GetTransform(current);
        txTarget.BeginAnimation(TranslateTransform.XProperty, null);
        txCurrent.BeginAnimation(TranslateTransform.XProperty, null);
        txTarget.X = forward ? w : -w;
        target.Visibility = Visibility.Visible;

        // 3 ─ Measure target height.
        target.Measure(new Size(w, double.PositiveInfinity));
        double tgtH = target.DesiredSize.Height;
        if (tgtH < 1) tgtH = curH;

        // 4 ─ GPU-cache both panels for the duration of the animation.
        current.CacheMode = new BitmapCache { SnapsToDevicePixels = true };
        target.CacheMode = new BitmapCache { SnapsToDevicePixels = true };

        // 5 ─ Build animations.
        var slideOut = MakeAnim(forward ? -w : w, dur, SlideEase);
        var slideIn = MakeAnim(0, dur, SlideEase);
        var heightAnim = MakeAnim(tgtH, dur, HeightEase);

        int oldIdx = _activeIndex;
        _activeIndex = index;

        // 6 ─ On completion: clean up.
        slideIn.Completed += (_, _) =>
        {
            var old = InternalChildren[oldIdx];
            old.Visibility = Visibility.Collapsed;
            old.CacheMode = null;
            target.CacheMode = null;

            var txOld = GetTransform(old);
            txOld.BeginAnimation(TranslateTransform.XProperty, null);
            txOld.X = 0;

            ClearHeightLock();
            _isAnimating = false;
            PanelChanged?.Invoke(this, index);
        };

        // 7 ─ Fire!
        txCurrent.BeginAnimation(TranslateTransform.XProperty, slideOut);
        txTarget.BeginAnimation(TranslateTransform.XProperty, slideIn);
        BeginAnimation(HeightProperty, heightAnim);
    }

    /// <summary>
    /// Instantly jump to <paramref name="index"/> without animation.
    /// Passing no argument resets to the first panel.
    /// </summary>
    public void Reset(int index = 0)
    {
        if (InternalChildren.Count == 0) return;
        if (index < 0 || index >= InternalChildren.Count) index = 0;

        _isAnimating = false;

        for (int i = 0; i < InternalChildren.Count; i++)
        {
            var child = InternalChildren[i];
            child.CacheMode = null;

            var tx = GetTransform(child);
            tx.BeginAnimation(TranslateTransform.XProperty, null);
            tx.X = 0;

            child.Visibility = i == index ? Visibility.Visible : Visibility.Collapsed;
        }

        ClearHeightLock();
        _activeIndex = index;
        InvalidateMeasure();
    }

    #endregion

    // ── Helpers ──────────────────────────────────────────────────────

    private void ClearHeightLock()
    {
        BeginAnimation(HeightProperty, null);
        ClearValue(HeightProperty);
        InvalidateMeasure();
    }

    private static void EnsureTransform(UIElement el)
    {
        if (el.RenderTransform is not TranslateTransform)
            el.RenderTransform = new TranslateTransform();
    }

    private static TranslateTransform GetTransform(UIElement el)
    {
        EnsureTransform(el);
        return (TranslateTransform)el.RenderTransform;
    }

    private static DoubleAnimation MakeAnim(double to, TimeSpan dur, IEasingFunction ease)
    {
        var a = new DoubleAnimation
        {
            To = to,
            Duration = new Duration(dur),
            EasingFunction = ease,
            FillBehavior = FillBehavior.HoldEnd
        };
        Timeline.SetDesiredFrameRate(a, 60);
        return a;
    }
}
