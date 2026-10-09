using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using AutoMidiPlayer.WPF.Services.MidiShow;
using AutoMidiPlayer.WPF.ViewModels;

namespace AutoMidiPlayer.WPF.Controls;

/// <summary>
/// A reusable account-management panel for any MIDI source site.
/// Uses <see cref="SlidingPanelHost"/> to animate between three views:
///   0 – Side-by-side action buttons
///   1 – Post-signup prompt
///   2 – Sign-in form
/// </summary>
public partial class AccountPanel : UserControl
{
    #region Dependency Properties

    public static readonly DependencyProperty SiteNameProperty =
        DependencyProperty.Register(
            nameof(SiteName), typeof(string), typeof(AccountPanel),
            new PropertyMetadata("MidiShow", (d, _) => (d as AccountPanel)?.UpdateHeaderText()));

    public string SiteName
    {
        get => (string)GetValue(SiteNameProperty);
        set => SetValue(SiteNameProperty, value);
    }

    public static readonly DependencyProperty SignUpUrlProperty =
        DependencyProperty.Register(
            nameof(SignUpUrl), typeof(string), typeof(AccountPanel),
            new PropertyMetadata("https://www.midishow.com/en/user/account/signup", (d, _) =>
            {
                if (d as AccountPanel is { } panel)
                {
                    panel.UpdateSignUpVisibility();
                }
            }));

    public string SignUpUrl
    {
        get => (string)GetValue(SignUpUrlProperty);
        set => SetValue(SignUpUrlProperty, value);
    }

    #endregion

    #region Routed Events

    public static readonly RoutedEvent CreateAccountClickedEvent =
        EventManager.RegisterRoutedEvent(nameof(CreateAccountClicked), RoutingStrategy.Bubble, typeof(RoutedEventHandler), typeof(AccountPanel));

    public event RoutedEventHandler CreateAccountClicked
    {
        add => AddHandler(CreateAccountClickedEvent, value);
        remove => RemoveHandler(CreateAccountClickedEvent, value);
    }

    public static readonly RoutedEvent RemoveAccountClickedEvent =
        EventManager.RegisterRoutedEvent(nameof(RemoveAccountClicked), RoutingStrategy.Bubble, typeof(RoutedEventHandler), typeof(AccountPanel));

    public event RoutedEventHandler RemoveAccountClicked
    {
        add => AddHandler(RemoveAccountClickedEvent, value);
        remove => RemoveHandler(RemoveAccountClickedEvent, value);
    }

    public static readonly RoutedEvent CopyCookiesClickedEvent =
        EventManager.RegisterRoutedEvent(nameof(CopyCookiesClicked), RoutingStrategy.Bubble, typeof(RoutedEventHandler), typeof(AccountPanel));

    public event RoutedEventHandler CopyCookiesClicked
    {
        add => AddHandler(CopyCookiesClickedEvent, value);
        remove => RemoveHandler(CopyCookiesClickedEvent, value);
    }

    #endregion

    public AccountPanel()
    {
        InitializeComponent();
        Loaded += (_, _) => { UpdateHeaderText(); UpdateSignUpVisibility(); };
        IsVisibleChanged += (_, e) => { if (e.NewValue is true) PanelSlider?.Reset(); };
    }

    #region Event Handlers

    private void CreateAccount_Click(object sender, RoutedEventArgs e)
    {
        RaiseEvent(new RoutedEventArgs(CreateAccountClickedEvent, this));
        OpenSignUpUrlSafely();
        PanelSlider.NavigateTo(1);
    }

    private void OpenSignUpPage_Click(object sender, RoutedEventArgs e)
        => OpenSignUpUrlSafely();

    /// <summary>
    /// Opens the signup URL in the default browser while temporarily
    /// locking the parent popup so it doesn't close when focus is lost.
    /// </summary>
    public event System.EventHandler? OpeningBrowser;

    private void OpenSignUpUrlSafely()
    {
        if (string.IsNullOrWhiteSpace(SignUpUrl)) return;

        // Fire event so the parent window knows to ignore the upcoming Deactivated event
        OpeningBrowser?.Invoke(this, System.EventArgs.Empty);

        OpenUrl(SignUpUrl);
    }

    private void SignInButton_Click(object sender, RoutedEventArgs e)
        => PanelSlider.NavigateTo(2);

    private void SignInLink_Click(object sender, RoutedEventArgs e)
        => PanelSlider.NavigateTo(2);

    private void RemoveAccount_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: MidiShowAccountRow row })
            (DataContext as OnlineMidiViewModel)?.RemoveAccount(row);

        RaiseEvent(new RoutedEventArgs(RemoveAccountClickedEvent, sender));
    }

    private void RefreshAccount_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: MidiShowAccountRow row })
            (DataContext as OnlineMidiViewModel)?.ResetAccountState(row);
    }

    private void CopyCookies_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: MidiShowAccountRow row })
            (DataContext as OnlineMidiViewModel)?.CopyCookies(row);

        RaiseEvent(new RoutedEventArgs(CopyCookiesClickedEvent, sender));
    }

    private void PasswordBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && DataContext is OnlineMidiViewModel vm)
        {
            e.Handled = true;
            _ = vm.AddPasswordAccount();
        }
    }

    #endregion

    #region Helpers

    private void UpdateHeaderText()
    {
        if (HeaderText is not null)
            HeaderText.Text = $"{SiteName} accounts";
        if (SignUpSiteNameRun is not null)
            SignUpSiteNameRun.Text = SiteName;
    }

    private void UpdateSignUpVisibility()
    {
        if (CreateAccountButton is not null)
            CreateAccountButton.Visibility = string.IsNullOrWhiteSpace(SignUpUrl)
                ? Visibility.Collapsed
                : Visibility.Visible;
    }

    private static void OpenUrl(string url)
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true
            });
        }
        catch { /* Silently ignored. */ }
    }

    /// <summary>Walk logical then visual tree upward to find an ancestor of type T.</summary>
    private static T? FindAncestor<T>(DependencyObject element) where T : DependencyObject
    {
        var current = element;
        while (current is not null)
        {
            if (current is T match) return match;
            current = LogicalTreeHelper.GetParent(current)
                      ?? (current is Visual v ? VisualTreeHelper.GetParent(v) : null);
        }
        return null;
    }

    #endregion
}
