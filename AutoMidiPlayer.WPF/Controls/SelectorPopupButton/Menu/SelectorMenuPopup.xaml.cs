using System;
using System.Collections;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using AutoMidiPlayer.WPF.Helpers;

namespace AutoMidiPlayer.WPF.Controls.SelectorPopupButton.Menu;

public partial class SelectorMenuPopup : UserControl
{
    public static readonly DependencyProperty PlacementTargetProperty =
        DependencyProperty.Register(nameof(PlacementTarget), typeof(UIElement), typeof(SelectorMenuPopup));

    public static readonly DependencyProperty IsOpenProperty =
        DependencyProperty.Register(
            nameof(IsOpen),
            typeof(bool),
            typeof(SelectorMenuPopup),
            new FrameworkPropertyMetadata(false, FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));

    public static readonly DependencyProperty ItemsSourceProperty =
        DependencyProperty.Register(nameof(ItemsSource), typeof(IEnumerable), typeof(SelectorMenuPopup));

    public static readonly DependencyProperty SelectedItemProperty =
        DependencyProperty.Register(
            nameof(SelectedItem),
            typeof(object),
            typeof(SelectorMenuPopup),
            new FrameworkPropertyMetadata(
                null,
                FrameworkPropertyMetadataOptions.BindsTwoWayByDefault,
                OnSelectedItemChanged));

    public static readonly DependencyProperty ItemTemplateProperty =
        DependencyProperty.Register(nameof(ItemTemplate), typeof(DataTemplate), typeof(SelectorMenuPopup));

    public static readonly DependencyProperty MaxPopupWidthProperty =
        DependencyProperty.Register(nameof(MaxPopupWidth), typeof(double), typeof(SelectorMenuPopup), new PropertyMetadata(220.0));

    public static readonly DependencyProperty MaxPopupHeightProperty =
        DependencyProperty.Register(nameof(MaxPopupHeight), typeof(double), typeof(SelectorMenuPopup), new PropertyMetadata(320.0));

    public static readonly DependencyProperty SelectedIndexProperty =
        DependencyProperty.Register(
            nameof(SelectedIndex),
            typeof(int),
            typeof(SelectorMenuPopup),
            new FrameworkPropertyMetadata(
                -1,
                FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));

    public static readonly DependencyProperty DisplayMemberPathProperty =
        DependencyProperty.Register(nameof(DisplayMemberPath), typeof(string), typeof(SelectorMenuPopup), new PropertyMetadata(null));

    public static readonly RoutedEvent SelectionChangedEvent = EventManager.RegisterRoutedEvent(
        nameof(SelectionChanged), RoutingStrategy.Bubble, typeof(SelectionChangedEventHandler), typeof(SelectorMenuPopup));

    public event SelectionChangedEventHandler SelectionChanged
    {
        add => AddHandler(SelectionChangedEvent, value);
        remove => RemoveHandler(SelectionChangedEvent, value);
    }

    public event EventHandler? Closed;

    public SelectorMenuPopup()
    {
        InitializeComponent();
        SelectorPopup.Placement = PlacementMode.Bottom;

        SelectorListBox.AddHandler(PreviewMouseWheelEvent, new MouseWheelEventHandler(PopupBorder_PreviewMouseWheel), true);
        SelectorListBox.AddHandler(MouseWheelEvent, new MouseWheelEventHandler(PopupBorder_PreviewMouseWheel), true);
    }

    public UIElement? PlacementTarget
    {
        get => (UIElement?)GetValue(PlacementTargetProperty);
        set => SetValue(PlacementTargetProperty, value);
    }

    public bool IsOpen
    {
        get => (bool)GetValue(IsOpenProperty);
        set => SetValue(IsOpenProperty, value);
    }

    public IEnumerable? ItemsSource
    {
        get => (IEnumerable?)GetValue(ItemsSourceProperty);
        set => SetValue(ItemsSourceProperty, value);
    }

    public object? SelectedItem
    {
        get => GetValue(SelectedItemProperty);
        set => SetValue(SelectedItemProperty, value);
    }

    public DataTemplate? ItemTemplate
    {
        get => (DataTemplate?)GetValue(ItemTemplateProperty);
        set => SetValue(ItemTemplateProperty, value);
    }

    public int SelectedIndex
    {
        get => (int)GetValue(SelectedIndexProperty);
        set => SetValue(SelectedIndexProperty, value);
    }

    public string DisplayMemberPath
    {
        get => (string)GetValue(DisplayMemberPathProperty);
        set => SetValue(DisplayMemberPathProperty, value);
    }

    public double MaxPopupWidth
    {
        get => (double)GetValue(MaxPopupWidthProperty);
        set => SetValue(MaxPopupWidthProperty, value);
    }

    public double MaxPopupHeight
    {
        get => (double)GetValue(MaxPopupHeightProperty);
        set => SetValue(MaxPopupHeightProperty, value);
    }

    public Task CloseWithAnimationAsync()
    {
        if (_isClosingAnimationRunning || !IsOpen)
            return Task.CompletedTask;

        _isClosingAnimationRunning = true;
        return CloseWithAnimationCoreAsync();
    }

    private const double PopupSpacing = 8d;

    private SmoothScrollAnimator? _scrollAnimator;
    private ScrollViewer? _popupScrollViewer;
    private bool _isClosingAnimationRunning;

    private static void OnSelectedItemChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is SelectorMenuPopup popup)
            popup.QueueCenterSelectedItem();
    }

    private void SelectorPopup_Opened(object sender, EventArgs e)
    {
        UpdatePopupPlacement();
        PlayOpenAnimation();
        QueueCenterSelectedItem();

        // Ensure wheel input is captured by the popup list
        SelectorListBox.Focus();
        Keyboard.Focus(SelectorListBox);

        EnsurePopupScrollViewer();
    }

    private void SelectorPopup_Closed(object sender, EventArgs e)
    {
        IsOpen = false;
        _isClosingAnimationRunning = false;
        _scrollAnimator?.Stop();
        Closed?.Invoke(this, EventArgs.Empty);
    }

    private void PlayOpenAnimation()
    {
        if (PopupSurface.RenderTransform is not TranslateTransform translateTransform)
        {
            translateTransform = new TranslateTransform();
            PopupSurface.RenderTransform = translateTransform;
        }

        var openOffset = SelectorPopup.Placement == PlacementMode.Top ? 8d : -8d;
        PopupSurface.Opacity = 0d;
        translateTransform.Y = openOffset;

        var easing = new System.Windows.Media.Animation.CubicEase { EasingMode = System.Windows.Media.Animation.EasingMode.EaseOut };
        PopupSurface.BeginAnimation(UIElement.OpacityProperty, new System.Windows.Media.Animation.DoubleAnimation
        {
            From = 0d,
            To = 1d,
            Duration = TimeSpan.FromMilliseconds(140),
            EasingFunction = easing
        });

        translateTransform.BeginAnimation(TranslateTransform.YProperty, new System.Windows.Media.Animation.DoubleAnimation
        {
            From = openOffset,
            To = 0d,
            Duration = TimeSpan.FromMilliseconds(160),
            EasingFunction = easing
        });
    }

    private async Task CloseWithAnimationCoreAsync()
    {
        var easing = new System.Windows.Media.Animation.CubicEase { EasingMode = System.Windows.Media.Animation.EasingMode.EaseIn };
        PopupSurface.BeginAnimation(UIElement.OpacityProperty, new System.Windows.Media.Animation.DoubleAnimation
        {
            To = 0d,
            Duration = TimeSpan.FromMilliseconds(110),
            EasingFunction = easing
        });

        await Task.Delay(120).ConfigureAwait(true);
        IsOpen = false;
        _isClosingAnimationRunning = false;
    }

    private void PopupBorder_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        // Popup must be open to handle wheel
        if (!SelectorPopup.IsOpen)
            return;

        // Check if mouse is actually over the popup
        if (!IsMouseOverPopup(e))
        {
            _ = CloseWithAnimationAsync();
            return;
        }

        // Mouse IS over popup - handle scrolling in the popup and consume the event
        e.Handled = true;

        ScrollPopupItems(e.Delta);
    }

    public bool IsMouseOverPopup(MouseEventArgs e)
    {
        if (SelectorListBox is not { } listBox)
            return false;

        try
        {
            // Only treat the actual item surface as popup-scrolling area.
            Point mousePos = e.GetPosition(listBox);

            if (mousePos.X < 0 || mousePos.X > listBox.ActualWidth ||
                mousePos.Y < 0 || mousePos.Y > listBox.ActualHeight)
                return false;

            return VisualTreeHelper.HitTest(listBox, mousePos) is not null;
        }
        catch
        {
            return false;
        }
    }

    private void QueueCenterSelectedItem()
    {
        if (!SelectorPopup.IsOpen)
            return;

        _ = Dispatcher.BeginInvoke(CenterSelectedItemIfScrollable, DispatcherPriority.Loaded);
    }

    private void UpdatePopupPlacement()
    {
        var openBelow = ShouldOpenBelow();
        SelectorPopup.Placement = openBelow ? PlacementMode.Bottom : PlacementMode.Top;
        SelectorPopup.VerticalOffset = openBelow ? PopupSpacing : -PopupSpacing;
    }

    private bool ShouldOpenBelow()
    {
        if (SelectorPopup.Child is not FrameworkElement popupContent || popupContent.ActualHeight <= 0)
            return true;

        if (PlacementTarget is not FrameworkElement target)
            return true;

        var window = Window.GetWindow(target);
        if (window is null || window.ActualHeight <= 0)
            return true;

        target.UpdateLayout();

        var targetTopLeft = target.TransformToAncestor(window).Transform(new Point(0d, 0d));
        var spaceAbove = targetTopLeft.Y;
        var spaceBelow = window.ActualHeight - (targetTopLeft.Y + target.ActualHeight);

        if (popupContent.ActualHeight <= spaceBelow)
            return true;

        if (popupContent.ActualHeight <= spaceAbove)
            return false;

        return spaceBelow >= spaceAbove;
    }

    private static bool IsSmoothScrollingEnabled()
    {
        if (Application.Current?.Resources["SmoothScrollingEnabled"] is bool isEnabled)
            return isEnabled;

        return true;
    }

    private void EnsurePopupScrollViewer()
    {
        var scrollViewer = GetPopupScrollViewer();
        if (scrollViewer is null)
            return;

        ScrollViewerAutoFadeBehavior.SetIsEnabled(scrollViewer, true);

        if (_scrollAnimator is null || !ReferenceEquals(_popupScrollViewer, scrollViewer))
        {
            _scrollAnimator?.Dispose();
            _scrollAnimator = new SmoothScrollAnimator(scrollViewer, SmoothScrollAnimatorOptions.Default);
        }

        _scrollAnimator.SyncTargetToCurrentOffset();
    }

    private ScrollViewer? GetPopupScrollViewer()
    {
        if (_popupScrollViewer is not null && IsDescendantOf(SelectorListBox, _popupScrollViewer))
            return _popupScrollViewer;

        SelectorListBox.ApplyTemplate();
        _popupScrollViewer = FindDescendant<ScrollViewer>(SelectorListBox);
        return _popupScrollViewer;
    }

    private void ScrollPopupItems(int wheelDelta)
    {
        var scrollViewer = GetPopupScrollViewer();
        if (scrollViewer is null)
            return;

        if (!IsSmoothScrollingEnabled())
        {
            var offset = scrollViewer.VerticalOffset - (wheelDelta * 0.5);
            scrollViewer.ScrollToVerticalOffset(Math.Clamp(offset, 0, scrollViewer.ScrollableHeight));
            return;
        }

        if (_scrollAnimator is null || !ReferenceEquals(_popupScrollViewer, scrollViewer))
            _scrollAnimator = new SmoothScrollAnimator(scrollViewer, SmoothScrollAnimatorOptions.Default);

        if (!_scrollAnimator.IsRunning)
            _scrollAnimator.SyncTargetToCurrentOffset();

        const double step = 40d;
        var deltaOffset = -(wheelDelta / 120d) * step;
        var currentOffset = scrollViewer.VerticalOffset;
        var maxLead = Math.Max(step * 10d, scrollViewer.ViewportHeight * 1.15d);
        var minTarget = Math.Max(0d, currentOffset - maxLead);
        var maxTarget = Math.Min(scrollViewer.ScrollableHeight, currentOffset + maxLead);

        _scrollAnimator.ApplyDelta(deltaOffset, minTarget, maxTarget, resetOnDirectionChange: true);
    }

    private void CenterSelectedItemIfScrollable()
    {
        if (!SelectorPopup.IsOpen || SelectorListBox.SelectedItem is null)
            return;

        SelectorListBox.UpdateLayout();
        SelectorListBox.ScrollIntoView(SelectorListBox.SelectedItem);
        SelectorListBox.UpdateLayout();

        if (GetPopupScrollViewer() is not ScrollViewer scrollViewer)
            return;

        if (scrollViewer.ScrollableHeight <= 0 || scrollViewer.ViewportHeight <= 0)
            return;

        int selectedIndex = SelectorListBox.SelectedIndex;
        if (selectedIndex < 0)
            return;

        var isLogicalScrollMode = ScrollViewer.GetCanContentScroll(SelectorListBox)
                                  && VirtualizingPanel.GetScrollUnit(SelectorListBox) != ScrollUnit.Pixel;
        if (isLogicalScrollMode)
        {
            double logicalOffset = selectedIndex - (scrollViewer.ViewportHeight / 2) + 0.5;
            double clampedLogicalOffset = Math.Clamp(logicalOffset, 0, scrollViewer.ScrollableHeight);
            scrollViewer.ScrollToVerticalOffset(clampedLogicalOffset);
            return;
        }

        if (SelectorListBox.ItemContainerGenerator.ContainerFromIndex(selectedIndex) is not FrameworkElement itemContainer)
            return;

        if (FindDescendant<ScrollContentPresenter>(scrollViewer) is not ScrollContentPresenter presenter)
            return;

        Point itemTop = itemContainer.TransformToAncestor(presenter).Transform(new Point(0, 0));
        double itemCenter = itemTop.Y + (itemContainer.ActualHeight / 2);
        double viewportCenter = presenter.ActualHeight / 2;
        double delta = itemCenter - viewportCenter;
        double targetOffset = Math.Clamp(scrollViewer.VerticalOffset + delta, 0, scrollViewer.ScrollableHeight);

        scrollViewer.ScrollToVerticalOffset(targetOffset);
    }

    private static T? FindDescendant<T>(DependencyObject root) where T : DependencyObject
    {
        int childrenCount = VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < childrenCount; i++)
        {
            DependencyObject child = VisualTreeHelper.GetChild(root, i);
            if (child is T target)
                return target;

            T? nested = FindDescendant<T>(child);
            if (nested is not null)
                return nested;
        }

        return null;
    }

    private static bool IsDescendantOf(DependencyObject ancestor, DependencyObject element)
    {
        var current = element;
        while (current != null)
        {
            if (ReferenceEquals(current, ancestor))
                return true;

            current = VisualTreeHelper.GetParent(current);
        }

        return false;
    }

    private static T? FindAncestor<T>(DependencyObject current) where T : DependencyObject
    {
        while (current != null)
        {
            if (current is T target)
                return target;

            current = VisualTreeHelper.GetParent(current);
        }

        return null;
    }

    private void SelectorListBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        RaiseEvent(new SelectionChangedEventArgs(SelectionChangedEvent, e.RemovedItems, e.AddedItems));

        if (SelectorPopup.IsOpen && e.AddedItems.Count > 0)
            _ = CloseWithAnimationAsync();
    }
}
