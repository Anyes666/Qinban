using System.Collections.Specialized;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
namespace QinBan.Desktop;

// Opt in only on the song list; native keyboard, scrollbar and touch panning stay in charge.
public static class SmoothScroll
{
    public static readonly DependencyProperty IsEnabledProperty = DependencyProperty.RegisterAttached(
        "IsEnabled", typeof(bool), typeof(SmoothScroll), new PropertyMetadata(false, EnabledChanged));
    private static readonly DependencyProperty StateProperty = DependencyProperty.RegisterAttached(
        "State", typeof(State), typeof(SmoothScroll));
    public static bool GetIsEnabled(DependencyObject target) => (bool)target.GetValue(IsEnabledProperty);
    public static void SetIsEnabled(DependencyObject target, bool value) => target.SetValue(IsEnabledProperty, value);
    private static void EnabledChanged(DependencyObject target, DependencyPropertyChangedEventArgs e)
    {
        if (target is not ListBox list) return;
        (list.GetValue(StateProperty) as State)?.Dispose();
        list.SetValue(StateProperty, (bool)e.NewValue ? new State(list) : null);
    }
    private sealed class State : IDisposable
    {
        private readonly ListBox _list;
        private ScrollViewer? _viewer;
        private readonly Stopwatch _clock = new();
        private bool _animating, _applying;
        private double _start, _target, _requested;
        private int _direction;
        private const double DurationMs = 180;
        public State(ListBox list)
        {
            _list = list; list.Loaded += Loaded; list.Unloaded += Unloaded;
            if (list.IsLoaded) Connect();
        }
        private void Loaded(object sender, RoutedEventArgs e) => Connect();
        private void Unloaded(object sender, RoutedEventArgs e) => Disconnect();
        private static ScrollViewer? FindViewer(DependencyObject root)
        {
            if (root is ScrollViewer viewer) return viewer;
            for (int i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
                if (FindViewer(VisualTreeHelper.GetChild(root, i)) is { } child) return child;
            return null;
        }
        private void Connect()
        {
            if (_viewer != null) return;
            _viewer = FindViewer(_list);
            if (_viewer == null) return;
            _list.PreviewMouseWheel += Wheel;
            _list.PreviewMouseDown += PointerDown;
            _list.PreviewTouchDown += TouchDown;
            _list.PreviewKeyDown += KeyDown;
            ((INotifyCollectionChanged)_list.Items).CollectionChanged += ItemsChanged;
            _viewer.ScrollChanged += ScrollChanged;
        }
        private void Disconnect()
        {
            Stop();
            if (_viewer == null) return;
            _list.PreviewMouseWheel -= Wheel;
            _list.PreviewMouseDown -= PointerDown;
            _list.PreviewTouchDown -= TouchDown;
            _list.PreviewKeyDown -= KeyDown;
            ((INotifyCollectionChanged)_list.Items).CollectionChanged -= ItemsChanged;
            _viewer.ScrollChanged -= ScrollChanged; _viewer = null;
        }
        private void Wheel(object sender, MouseWheelEventArgs e)
        {
            if (e.Handled || _viewer == null || _viewer.ScrollableHeight <= 0 || e.Delta == 0) return;
            int lines = SystemParameters.WheelScrollLines;
            if (lines == 0) return;
            double distance = lines < 0 ? _viewer.ViewportHeight : lines * 24.0;
            double delta = -e.Delta / 120.0 * distance;
            int direction = Math.Sign(delta);
            // Accumulate bursts, but a direction change starts from the visible position.
            double basis = _animating && direction == _direction ? _target : _viewer.VerticalOffset;
            _start = _viewer.VerticalOffset;
            _target = Math.Clamp(basis + delta, 0, _viewer.ScrollableHeight);
            _direction = direction; e.Handled = true;
            if (Math.Abs(_target - _start) < .01) { Stop(); return; }
            _requested = _start; _clock.Restart();
            if (!_animating) { _animating = true; CompositionTarget.Rendering += Render; }
        }
        private void Render(object? sender, EventArgs e)
        {
            if (_viewer == null) { Stop(); return; }
            double progress = Math.Clamp(_clock.Elapsed.TotalMilliseconds / DurationMs, 0, 1);
            double eased = 1 - Math.Pow(1 - progress, 3);
            _requested = Math.Clamp(_start + (_target - _start) * eased, 0, _viewer.ScrollableHeight);
            _applying = true;
            try { _viewer.ScrollToVerticalOffset(_requested); }
            finally { _applying = false; }
            if (progress >= 1) Stop();
        }
        private void ScrollChanged(object sender, ScrollChangedEventArgs e)
        {
            if (!_animating || _applying || _viewer == null) return;
            // ScrollChanged is delivered after layout; do not mistake our queued frame for user input.
            if (e.ExtentHeightChange != 0 || e.ViewportHeightChange != 0
                || (e.VerticalChange != 0 && Math.Abs(_viewer.VerticalOffset - _requested) > .5)) Stop();
        }
        private void PointerDown(object sender, MouseButtonEventArgs e) => Stop();
        private void TouchDown(object? sender, TouchEventArgs e) => Stop();
        private void KeyDown(object sender, KeyEventArgs e) => Stop();
        private void ItemsChanged(object? sender, NotifyCollectionChangedEventArgs e) => Stop();
        private void Stop()
        {
            if (_animating) CompositionTarget.Rendering -= Render;
            _animating = false; _clock.Stop();
        }
        public void Dispose() { Disconnect(); _list.Loaded -= Loaded; _list.Unloaded -= Unloaded; }
    }
}
