using System;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace AutoMidiPlayer.WPF.Controls;

public partial class Numberbox : UserControl
{
    // Chevron column width (20px button + 2px right margin) + border (1px each side) + text left padding (8px)
    private const double NonTextWidth = 20 + 2 + 2 + 8 + 4; // chevrons + border + padding + caret slack

    public static readonly DependencyProperty ValueProperty = DependencyProperty.Register(
        nameof(Value),
        typeof(double),
        typeof(Numberbox),
        new FrameworkPropertyMetadata(
            0.0,
            FrameworkPropertyMetadataOptions.BindsTwoWayByDefault,
            OnValueChanged,
            CoerceValue));

    public static readonly DependencyProperty MinimumProperty = DependencyProperty.Register(
        nameof(Minimum),
        typeof(double),
        typeof(Numberbox),
        new PropertyMetadata(double.MinValue, OnBoundsChanged));

    public static readonly DependencyProperty MaximumProperty = DependencyProperty.Register(
        nameof(Maximum),
        typeof(double),
        typeof(Numberbox),
        new PropertyMetadata(double.MaxValue, OnBoundsChanged));

    public static readonly DependencyProperty StepProperty = DependencyProperty.Register(
        nameof(Step),
        typeof(double),
        typeof(Numberbox),
        new PropertyMetadata(1.0));

    public static readonly DependencyProperty MaxDecimalPlacesProperty = DependencyProperty.Register(
        nameof(MaxDecimalPlaces),
        typeof(int),
        typeof(Numberbox),
        new PropertyMetadata(0, OnMaxDecimalPlacesChanged));

    public static readonly DependencyProperty IsGlowActiveProperty = DependencyProperty.Register(
        nameof(IsGlowActive),
        typeof(bool),
        typeof(Numberbox),
        new PropertyMetadata(false));

    public static readonly DependencyProperty IsInvalidProperty = DependencyProperty.Register(
        nameof(IsInvalid),
        typeof(bool),
        typeof(Numberbox),
        new PropertyMetadata(false));

    public static readonly DependencyProperty TextValueProperty = DependencyProperty.Register(
        nameof(TextValue),
        typeof(string),
        typeof(Numberbox),
        new FrameworkPropertyMetadata(
            "0",
            FrameworkPropertyMetadataOptions.BindsTwoWayByDefault,
            OnTextValueChanged));

    public static readonly DependencyProperty PlaceholderTextProperty = DependencyProperty.Register(
        nameof(PlaceholderText),
        typeof(string),
        typeof(Numberbox),
        new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty FixedWidthProperty = DependencyProperty.Register(
        nameof(FixedWidth),
        typeof(bool),
        typeof(Numberbox),
        new PropertyMetadata(false, OnFixedWidthChanged));

    public static readonly RoutedEvent ValueChangedEvent = EventManager.RegisterRoutedEvent(
        nameof(ValueChanged), RoutingStrategy.Bubble, typeof(RoutedPropertyChangedEventHandler<double>), typeof(Numberbox));

    private readonly DispatcherTimer _glowTimer = new()
    {
        Interval = TimeSpan.FromMilliseconds(450)
    };

    private bool _isLoaded;
    private bool _isSyncingText;
    private bool _isTextBoxFocused;

    public event RoutedPropertyChangedEventHandler<double> ValueChanged
    {
        add => AddHandler(ValueChangedEvent, value);
        remove => RemoveHandler(ValueChangedEvent, value);
    }

    public Numberbox()
    {
        InitializeComponent();

        _glowTimer.Tick += (_, _) =>
        {
            _glowTimer.Stop();
            IsGlowActive = false;
        };

        Loaded += (_, _) =>
        {
            _isLoaded = true;
            SyncTextFromValue();
            UpdateFixedMinWidth();
            UpdateMaxLength();
        };
    }

    public double Value
    {
        get => (double)GetValue(ValueProperty);
        set => SetValue(ValueProperty, value);
    }

    public double Minimum
    {
        get => (double)GetValue(MinimumProperty);
        set => SetValue(MinimumProperty, value);
    }

    public double Maximum
    {
        get => (double)GetValue(MaximumProperty);
        set => SetValue(MaximumProperty, value);
    }

    public double Step
    {
        get => (double)GetValue(StepProperty);
        set => SetValue(StepProperty, value);
    }

    public int MaxDecimalPlaces
    {
        get => (int)GetValue(MaxDecimalPlacesProperty);
        set => SetValue(MaxDecimalPlacesProperty, value);
    }

    public bool IsGlowActive
    {
        get => (bool)GetValue(IsGlowActiveProperty);
        set => SetValue(IsGlowActiveProperty, value);
    }

    public bool IsInvalid
    {
        get => (bool)GetValue(IsInvalidProperty);
        set => SetValue(IsInvalidProperty, value);
    }

    public string TextValue
    {
        get => (string)GetValue(TextValueProperty);
        set => SetValue(TextValueProperty, value);
    }

    public string PlaceholderText
    {
        get => (string)GetValue(PlaceholderTextProperty);
        set => SetValue(PlaceholderTextProperty, value);
    }

    /// <summary>
    /// When true, the control's MinWidth is locked to accommodate the widest
    /// of Minimum/Maximum formatted strings, preventing resize as value changes.
    /// </summary>
    public bool FixedWidth
    {
        get => (bool)GetValue(FixedWidthProperty);
        set => SetValue(FixedWidthProperty, value);
    }

    private static void OnValueChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not Numberbox nb)
            return;

        var oldVal = (double)e.OldValue;
        var newVal = (double)e.NewValue;

        nb.SyncTextFromValue();
        nb.IsInvalid = false;

        if (nb._isLoaded)
        {
            nb.TriggerGlow();
            nb.RaiseEvent(new RoutedPropertyChangedEventArgs<double>(oldVal, newVal, ValueChangedEvent));
        }
    }

    private static object CoerceValue(DependencyObject d, object baseValue)
    {
        if (d is not Numberbox nb)
            return baseValue;

        var val = (double)baseValue;
        val = Math.Max(nb.Minimum, Math.Min(nb.Maximum, val));
        return Math.Round(val, nb.MaxDecimalPlaces);
    }

    private static void OnBoundsChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not Numberbox nb)
            return;

        nb.CoerceValue(ValueProperty);
        nb.UpdateFixedMinWidth();
        nb.UpdateMaxLength();
    }

    private static void OnMaxDecimalPlacesChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not Numberbox nb)
            return;

        nb.CoerceValue(ValueProperty);
        nb.UpdateFixedMinWidth();
        nb.UpdateMaxLength();
    }

    private static void OnFixedWidthChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is Numberbox nb)
            nb.UpdateFixedMinWidth();
    }

    private static void OnTextValueChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not Numberbox nb || nb._isSyncingText)
            return;

        nb.ValidateAndApplyText((string)e.NewValue);
    }

    private string FormatValue(double val)
    {
        return MaxDecimalPlaces > 0
            ? val.ToString($"F{MaxDecimalPlaces}", CultureInfo.InvariantCulture)
            : ((long)val).ToString(CultureInfo.InvariantCulture);
    }

    private void SyncTextFromValue()
    {
        _isSyncingText = true;
        try
        {
            TextValue = FormatValue(Value);
        }
        finally
        {
            _isSyncingText = false;
        }
    }

    /// <summary>
    /// Measures the pixel width of a text string using the TextBox's font settings.
    /// </summary>
    private double MeasureTextWidth(string text)
    {
        var typeface = new Typeface(
            ValueTextBox.FontFamily,
            ValueTextBox.FontStyle,
            ValueTextBox.FontWeight,
            ValueTextBox.FontStretch);

        var formatted = new FormattedText(
            text,
            CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight,
            typeface,
            ValueTextBox.FontSize,
            Brushes.Black,
            VisualTreeHelper.GetDpi(this).PixelsPerDip);

        return formatted.WidthIncludingTrailingWhitespace;
    }

    /// <summary>
    /// When FixedWidth is enabled, computes and sets MinWidth on this control
    /// based on the widest min/max formatted string + chrome.
    /// </summary>
    private void UpdateFixedMinWidth()
    {
        if (!_isLoaded)
            return;

        if (!FixedWidth)
        {
            ClearValue(MinWidthProperty);
            return;
        }

        var minText = FormatValue(Minimum is double.MinValue ? 0 : Minimum);
        var maxText = FormatValue(Maximum is double.MaxValue ? 0 : Maximum);

        var minWidth = MeasureTextWidth(minText);
        var maxWidth = MeasureTextWidth(maxText);

        var widest = Math.Max(minWidth, maxWidth);
        MinWidth = Math.Ceiling(widest + NonTextWidth);
    }

    /// <summary>
    /// Calculates and sets MaxLength on the TextBox based on the
    /// formatted Minimum/Maximum strings. The '-' sign is not counted
    /// toward the digit limit — an extra character is added if negative
    /// values are allowed.
    /// </summary>
    private void UpdateMaxLength()
    {
        if (!_isLoaded)
            return;

        const int defaultMaxLength = 9;
        var allowNegative = Minimum < 0;
        var signChar = allowNegative ? 1 : 0;

        // Only limit character length when an explicit Maximum is set
        if (Maximum is double.MaxValue)
        {
            ValueTextBox.MaxLength = defaultMaxLength + signChar;
            return;
        }

        // Format absolute values to get digit count (excluding sign)
        var minAbs = Minimum is double.MinValue ? 0 : Math.Abs(Minimum);
        var maxAbs = Math.Abs(Maximum);

        var minDigits = FormatValue(minAbs).Length;
        var maxDigits = FormatValue(maxAbs).Length;
        var digitLength = Math.Max(minDigits, maxDigits);

        ValueTextBox.MaxLength = digitLength + signChar;
    }

    private void ValidateAndApplyText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            // Empty while typing is fine, will revert on commit
            return;
        }

        // Allow typing a minus sign or just a dot without marking invalid immediately
        if (text is "-" or "." or "-.")
        {
            IsInvalid = false;
            return;
        }

        if (!double.TryParse(text, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var parsed))
        {
            IsInvalid = true;
            return;
        }

        // Out of bounds — show red border/text, don't apply
        if (parsed < Minimum || parsed > Maximum)
        {
            IsInvalid = true;
            return;
        }

        IsInvalid = false;
        var rounded = Math.Round(parsed, MaxDecimalPlaces);
        _isSyncingText = true;
        try
        {
            Value = rounded;
        }
        finally
        {
            _isSyncingText = false;
        }
    }

    private void CommitText()
    {
        if (string.IsNullOrWhiteSpace(TextValue) ||
            !double.TryParse(TextValue, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var parsed))
        {
            // Revert to current value on invalid commit
            SyncTextFromValue();
            IsInvalid = false;
            return;
        }

        var clamped = Math.Max(Minimum, Math.Min(Maximum, parsed));
        var rounded = Math.Round(clamped, MaxDecimalPlaces);

        _isSyncingText = true;
        try
        {
            Value = rounded;
        }
        finally
        {
            _isSyncingText = false;
        }

        SyncTextFromValue();
        IsInvalid = false;
    }

    private void Increment()
    {
        var newVal = Math.Round(Value + Step, MaxDecimalPlaces);
        if (newVal <= Maximum)
            Value = newVal;
        else
            Value = Maximum;
    }

    private void Decrement()
    {
        var newVal = Math.Round(Value - Step, MaxDecimalPlaces);
        if (newVal >= Minimum)
            Value = newVal;
        else
            Value = Minimum;
    }

    private void TriggerGlow()
    {
        IsGlowActive = true;
        _glowTimer.Stop();
        _glowTimer.Start();
    }

    private void UpButton_Click(object sender, RoutedEventArgs e)
    {
        Increment();
        e.Handled = true;
    }

    private void DownButton_Click(object sender, RoutedEventArgs e)
    {
        Decrement();
        e.Handled = true;
    }

    private void ValueTextBox_GotFocus(object sender, RoutedEventArgs e)
    {
        _isTextBoxFocused = true;
    }

    private void ValueTextBox_LostFocus(object sender, RoutedEventArgs e)
    {
        _isTextBoxFocused = false;
        CommitText();
    }

    private void ValueTextBox_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        switch (e.Key)
        {
            case Key.Up:
                Increment();
                e.Handled = true;
                break;
            case Key.Down:
                Decrement();
                e.Handled = true;
                break;
            case Key.Enter:
                CommitText();
                Keyboard.ClearFocus();
                e.Handled = true;
                break;
            case Key.Escape:
                SyncTextFromValue();
                IsInvalid = false;
                Keyboard.ClearFocus();
                e.Handled = true;
                break;
        }
    }

    private void Root_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (!_isTextBoxFocused)
            return;

        if (e.Delta > 0)
            Increment();
        else if (e.Delta < 0)
            Decrement();

        e.Handled = true;
    }
}
