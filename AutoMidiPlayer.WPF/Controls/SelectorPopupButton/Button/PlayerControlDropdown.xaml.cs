using System;
using System.Collections;
using System.Windows;
using System.Windows.Controls;

namespace AutoMidiPlayer.WPF.Controls.SelectorPopupButton.Button;

public partial class PlayerControlDropdown : UserControl
{
    public static readonly DependencyProperty ButtonContentProperty =
        DependencyProperty.Register(nameof(ButtonContent), typeof(object), typeof(PlayerControlDropdown));

    public static readonly DependencyProperty ItemsSourceProperty =
        DependencyProperty.Register(nameof(ItemsSource), typeof(IEnumerable), typeof(PlayerControlDropdown));

    public static readonly DependencyProperty SelectedItemProperty =
        DependencyProperty.Register(
            nameof(SelectedItem),
            typeof(object),
            typeof(PlayerControlDropdown),
            new FrameworkPropertyMetadata(
                null,
                FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));

    public static readonly DependencyProperty ItemTemplateProperty =
        DependencyProperty.Register(nameof(ItemTemplate), typeof(DataTemplate), typeof(PlayerControlDropdown));

    public static readonly DependencyProperty PopupMaxWidthProperty =
        DependencyProperty.Register(nameof(PopupMaxWidth), typeof(double), typeof(PlayerControlDropdown), new PropertyMetadata(220.0));

    public static readonly DependencyProperty PopupMaxHeightProperty =
        DependencyProperty.Register(nameof(PopupMaxHeight), typeof(double), typeof(PlayerControlDropdown), new PropertyMetadata(320.0));

    public static readonly DependencyProperty IsActiveProperty =
        DependencyProperty.Register(nameof(IsActive), typeof(bool), typeof(PlayerControlDropdown), new PropertyMetadata(false));

    private DateTime _lastPopupCloseTime = DateTime.MinValue;

    public PlayerControlDropdown()
    {
        InitializeComponent();
        MenuPopup.Closed += (_, _) => _lastPopupCloseTime = DateTime.UtcNow;
    }

    public object? ButtonContent
    {
        get => GetValue(ButtonContentProperty);
        set => SetValue(ButtonContentProperty, value);
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

    public double PopupMaxWidth
    {
        get => (double)GetValue(PopupMaxWidthProperty);
        set => SetValue(PopupMaxWidthProperty, value);
    }

    public double PopupMaxHeight
    {
        get => (double)GetValue(PopupMaxHeightProperty);
        set => SetValue(PopupMaxHeightProperty, value);
    }

    public bool IsActive
    {
        get => (bool)GetValue(IsActiveProperty);
        set => SetValue(IsActiveProperty, value);
    }

    private void SelectorButton_Click(object sender, RoutedEventArgs e)
    {
        if (!MenuPopup.IsOpen && (DateTime.UtcNow - _lastPopupCloseTime).TotalMilliseconds < 250)
        {
            e.Handled = true;
            return;
        }

        MenuPopup.IsOpen = !MenuPopup.IsOpen;
        e.Handled = true;
    }

    protected override void OnPreviewMouseWheel(System.Windows.Input.MouseWheelEventArgs e)
    {
        base.OnPreviewMouseWheel(e);
        if (e.Handled || MenuPopup.IsOpen) return;

        if (ItemsSource is IList list && list.Count > 0)
        {
            int index = list.IndexOf(SelectedItem);
            if (e.Delta < 0 && index < list.Count - 1)
            {
                SelectedItem = list[index + 1];
                e.Handled = true;
            }
            else if (e.Delta > 0 && index > 0)
            {
                SelectedItem = list[index - 1];
                e.Handled = true;
            }
            else
            {
                e.Handled = true;
            }
        }
        else if (ItemsSource != null)
        {
            e.Handled = true;
        }
    }
}
