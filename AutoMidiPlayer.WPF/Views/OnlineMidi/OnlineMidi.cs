using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using AutoMidiPlayer.WPF.Helpers;
using AutoMidiPlayer.WPF.Services.MidiShow;
using AutoMidiPlayer.WPF.Services.OnlineMidi;
using AutoMidiPlayer.WPF.ViewModels;

namespace AutoMidiPlayer.WPF.Views;

public partial class OnlineMidiView : UserControl
{
    private ScrollViewer? _resultsScrollViewer;
    private SmoothScrollAnimator? _scrollAnimator;

    public OnlineMidiView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
        ResultsList.Loaded += ResultsList_Loaded;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        var window = Window.GetWindow(this);
        if (window != null)
        {
            window.PreviewMouseDown += Window_PreviewMouseDown;
            window.Deactivated += Window_Deactivated;
            window.Activated += Window_Activated;
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        var window = Window.GetWindow(this);
        if (window != null)
        {
            window.PreviewMouseDown -= Window_PreviewMouseDown;
            window.Deactivated -= Window_Deactivated;
            window.Activated -= Window_Activated;
        }
    }

    private void Window_PreviewMouseDown(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (DataContext is not OnlineMidiViewModel { IsAccountFlyoutOpen: true } vm) return;

        var posPopup = e.GetPosition(PopupBorder);
        bool inPopup = posPopup.X >= 0 && posPopup.Y >= 0 && posPopup.X <= PopupBorder.ActualWidth && posPopup.Y <= PopupBorder.ActualHeight;

        if (inPopup) return; // Click inside the popup content — do nothing.

        // Check if the click landed on the toggle button (inside AccountAnchor).
        var posAnchor = e.GetPosition(AccountAnchor);
        bool inAnchor = posAnchor.X >= 0 && posAnchor.Y >= 0 && posAnchor.X <= AccountAnchor.ActualWidth && posAnchor.Y <= AccountAnchor.ActualHeight;

        // Close the popup. If the click was on the toggle button, mark the event
        // as handled so the button's ToggleAccountFlyout command doesn't fire
        // and immediately reopen it.
        vm.IsAccountFlyoutOpen = false;
        if (inAnchor)
        {
            e.Handled = true;
        }
    }

    /// <summary>
    /// When true, the next Window.Deactivated event will NOT close the popup.
    /// Set by AccountPanel when it opens a browser URL so the panel stays visible.
    /// </summary>
    internal bool _keepOpenOnDeactivate;

    private void AccountPanel_OpeningBrowser(object? sender, EventArgs e)
    {
        _keepOpenOnDeactivate = true;
    }

    private void Window_Activated(object? sender, EventArgs e)
    {
        _keepOpenOnDeactivate = false;
    }

    private void Window_Deactivated(object? sender, EventArgs e)
    {
        if (_keepOpenOnDeactivate)
        {
            return;
        }

        if (DataContext is OnlineMidiViewModel { IsAccountFlyoutOpen: true } vm)
        {
            vm.IsAccountFlyoutOpen = false;
        }
    }

    private void ResultsList_Loaded(object sender, RoutedEventArgs e)
    {
        if (_resultsScrollViewer != null)
        {
            _resultsScrollViewer.PreviewMouseWheel -= ResultsScrollViewer_PreviewMouseWheel;
            _resultsScrollViewer.PreviewMouseDown -= ResultsScrollViewer_PreviewMouseDown;
        }

        _resultsScrollViewer = FindVisualChild<ScrollViewer>(ResultsList);
        if (_resultsScrollViewer is null)
            return;

        // Apply the custom scrollbar and smooth scroll behavior programmatically,
        // because the WPF UI library's ListBox template prevents the global implicit
        // ScrollViewer style (from BaseStyles.xaml) from reaching the internal ScrollViewer.
        ScrollViewerAutoFadeBehavior.SetIsEnabled(_resultsScrollViewer, true);
        ScrollEdgeFadeBehavior.SetIsEnabled(_resultsScrollViewer, true);
        _resultsScrollViewer.Padding = new Thickness(0, 0, 12, 0);

        _scrollAnimator = new SmoothScrollAnimator(_resultsScrollViewer, SmoothScrollAnimatorOptions.Default);
        _resultsScrollViewer.PreviewMouseWheel += ResultsScrollViewer_PreviewMouseWheel;
        _resultsScrollViewer.PreviewMouseDown += ResultsScrollViewer_PreviewMouseDown;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is OnlineMidiViewModel oldVm)
            oldVm.PropertyChanged -= ViewModel_PropertyChanged;
        if (e.NewValue is OnlineMidiViewModel newVm)
            newVm.PropertyChanged += ViewModel_PropertyChanged;
    }

    private void ViewModel_PropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(OnlineMidiViewModel.CurrentPage))
        {
            ScrollToTop();
        }
        else if (e.PropertyName == nameof(OnlineMidiViewModel.IsAccountFlyoutOpen))
        {
            HandleFlyoutOpenChanged();
        }
    }

    private void ScrollToTop()
    {
        if (_scrollAnimator != null && _resultsScrollViewer != null)
        {
            _scrollAnimator.SyncTargetToCurrentOffset();
            _scrollAnimator.SetTargetOffset(0, startIfNeeded: true, immediateStep: false);
        }
        else
        {
            _resultsScrollViewer?.ScrollToTop();
        }
    }

    private void ResultsScrollViewer_PreviewMouseWheel(object sender, System.Windows.Input.MouseWheelEventArgs e)
    {
        _scrollAnimator?.Stop();
    }

    private void ResultsScrollViewer_PreviewMouseDown(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        _scrollAnimator?.Stop();
    }

    private static T? FindVisualChild<T>(DependencyObject parent) where T : DependencyObject
    {
        for (int i = 0; i < System.Windows.Media.VisualTreeHelper.GetChildrenCount(parent); i++)
        {
            var child = System.Windows.Media.VisualTreeHelper.GetChild(parent, i);
            if (child is T match)
                return match;

            var descendent = FindVisualChild<T>(child);
            if (descendent != null)
                return descendent;
        }
        return null;
    }

    private OnlineMidiViewModel? ViewModel => DataContext as OnlineMidiViewModel;

    private void SearchBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && ViewModel is { } vm)
        {
            e.Handled = true;
            _ = vm.Search();
        }
    }

    private void PageInput_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && sender is TextBox tb && ViewModel is { } vm)
        {
            e.Handled = true;
            if (int.TryParse(tb.Text, out int page))
            {
                _ = vm.GoToPage(page);
            }
            else
            {
                tb.Text = vm.CurrentPage.ToString();
            }
            Keyboard.ClearFocus();
        }
    }



    private void AddToSongs_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm)
            return;

        if (sender is FrameworkElement { DataContext: OnlineMidiItem item })
            _ = vm.AddToSongsAsync(item);
    }

    private void Preview_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm)
            return;

        if (sender is FrameworkElement { DataContext: OnlineMidiItem item })
            _ = vm.PreviewAsync(item);
    }


    private void Card_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm)
            return;

        if (sender is FrameworkElement { DataContext: OnlineMidiItem item })
            _ = vm.ToggleDetailsAsync(item);
    }
    #region Account Popup Animations

    private bool _isPlayingPopupExit;

    /// <summary>
    /// Reacts to ViewModel.IsAccountFlyoutOpen changes.
    /// Open  → set IsOpen = true  (Opened handler plays intro + removes topmost).
    /// Close → play outro first, then set IsOpen = false.
    /// </summary>
    private void HandleFlyoutOpenChanged()
    {
        if (DataContext is not OnlineMidiViewModel vm) return;

        if (vm.IsAccountFlyoutOpen)
        {
            if (!AccountPopup.IsOpen)
            {
                AccountPopup.IsOpen = true;
            }
            else if (_isPlayingPopupExit)
            {
                // If it's currently closing, it will re-evaluate at the end of the outro.
                // But let's interrupt the exit if possible, or just let it finish and re-open.
            }
        }
        else if (AccountPopup.IsOpen && !_isPlayingPopupExit)
        {
            _isPlayingPopupExit = true;
            PlayPopupOutro(() =>
            {
                _isPlayingPopupExit = false;

                // Only close if the ViewModel still says it should be closed.
                if (DataContext is OnlineMidiViewModel { IsAccountFlyoutOpen: false })
                {
                    AccountPopup.IsOpen = false;
                    ResetPopupTransforms();
                }
                else
                {
                    // The user clicked to reopen while it was closing.
                    PlayPopupIntro();
                }
            });
        }
    }

    /// <summary>
    /// Forces the popup to always appear right-aligned below the anchor,
    /// ignoring WPF's automatic screen-edge repositioning that shifts the top edge.
    /// </summary>
    private System.Windows.Controls.Primitives.CustomPopupPlacement[] AccountPopup_CustomPlacement(
        Size popupSize, Size targetSize, Point offset)
    {
        // Right-align: shift left so popup's right edge aligns with anchor's right edge.
        double x = targetSize.Width - popupSize.Width;
        // Place directly below the anchor with a 6px gap.
        double y = targetSize.Height + 6;

        return
        [
            new System.Windows.Controls.Primitives.CustomPopupPlacement(
                new Point(x, y),
                System.Windows.Controls.Primitives.PopupPrimaryAxis.Vertical)
        ];
    }

    private void AccountPopup_Opened(object? sender, EventArgs e)
    {
        if (sender is not System.Windows.Controls.Primitives.Popup popup) return;

        // Remove TOPMOST so the popup stays within the app's z-order.
        RemovePopupTopmost(popup);

        // Dispatch the intro animation so the PopupBorder has finished layout.
        if (!_isPlayingPopupExit)
        {
            Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded, PlayPopupIntro);
        }
    }

    // ── Intro: slide down + scale up + fade in ──────────────────────
    private void PlayPopupIntro()
    {
        var border = PopupBorder;
        var transforms = (System.Windows.Media.TransformGroup)border.RenderTransform;
        var translate = (System.Windows.Media.TranslateTransform)transforms.Children[1];
        var scale = (System.Windows.Media.ScaleTransform)transforms.Children[0];

        var ease = new System.Windows.Media.Animation.CubicEase
            { EasingMode = System.Windows.Media.Animation.EasingMode.EaseOut };

        var slideDown = new System.Windows.Media.Animation.DoubleAnimation(-12, 0,
            TimeSpan.FromMilliseconds(220)) { EasingFunction = ease };
        var scaleUp = new System.Windows.Media.Animation.DoubleAnimation(0.96, 1,
            TimeSpan.FromMilliseconds(220)) { EasingFunction = ease };
        var fadeIn = new System.Windows.Media.Animation.DoubleAnimation(0, 1,
            TimeSpan.FromMilliseconds(180)) { EasingFunction = ease };

        translate.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty, slideDown);
        scale.BeginAnimation(System.Windows.Media.ScaleTransform.ScaleYProperty, scaleUp);
        border.BeginAnimation(OpacityProperty, fadeIn);
    }

    // ── Outro: slide up + scale down + fade out ─────────────────────
    private void PlayPopupOutro(Action onCompleted)
    {
        var border = PopupBorder;
        var transforms = (System.Windows.Media.TransformGroup)border.RenderTransform;
        var translate = (System.Windows.Media.TranslateTransform)transforms.Children[1];
        var scale = (System.Windows.Media.ScaleTransform)transforms.Children[0];

        var ease = new System.Windows.Media.Animation.CubicEase
            { EasingMode = System.Windows.Media.Animation.EasingMode.EaseIn };

        var slideUp = new System.Windows.Media.Animation.DoubleAnimation(-12,
            TimeSpan.FromMilliseconds(150)) { EasingFunction = ease };
        var scaleDown = new System.Windows.Media.Animation.DoubleAnimation(0.96,
            TimeSpan.FromMilliseconds(150)) { EasingFunction = ease };
        var fadeOut = new System.Windows.Media.Animation.DoubleAnimation(0,
            TimeSpan.FromMilliseconds(120)) { EasingFunction = ease };

        fadeOut.Completed += (_, _) => onCompleted();

        translate.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty, slideUp);
        scale.BeginAnimation(System.Windows.Media.ScaleTransform.ScaleYProperty, scaleDown);
        border.BeginAnimation(OpacityProperty, fadeOut);
    }

    private void ResetPopupTransforms()
    {
        var border = PopupBorder;
        var transforms = (System.Windows.Media.TransformGroup)border.RenderTransform;
        var translate = (System.Windows.Media.TranslateTransform)transforms.Children[1];
        var scale = (System.Windows.Media.ScaleTransform)transforms.Children[0];

        // Clear any running animations
        translate.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty, null);
        scale.BeginAnimation(System.Windows.Media.ScaleTransform.ScaleYProperty, null);
        border.BeginAnimation(OpacityProperty, null);

        // Reset to the PRE-animation (hidden) state, not the visible state.
        // This prevents a flash of fully-visible content when the popup reopens,
        // since WPF shows the popup before our intro animation can start.
        translate.Y = -12;
        scale.ScaleY = 0.96;
        border.Opacity = 0;
    }

    #endregion

    #region Win32 Interop

    private static void RemovePopupTopmost(System.Windows.Controls.Primitives.Popup popup)
    {
        var source = System.Windows.PresentationSource.FromVisual(popup.Child)
                         as System.Windows.Interop.HwndSource;
        if (source?.Handle is not { } hwnd || hwnd == nint.Zero) return;

        SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE);
    }

    private static readonly nint HWND_NOTOPMOST = -2;
    private const uint SWP_NOACTIVATE = 0x0010;
    private const uint SWP_NOMOVE     = 0x0002;
    private const uint SWP_NOSIZE     = 0x0001;

    [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(nint hWnd, nint hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);

    #endregion
}
