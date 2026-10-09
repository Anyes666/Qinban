using System;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using AutoMidiPlayer.WPF.Helpers;
using Wpf.Ui.Controls;

namespace AutoMidiPlayer.WPF.Dialogs;

public partial class UpdateProgressDialog : ContentDialog, INotifyPropertyChanged
{
    private string _progressText = "Preparing...";
    private string _progressDetailText = "";
    private double _progressPercentage = 0;
    private bool _isProgressIndeterminate = false;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string ProgressText
    {
        get => _progressText;
        set
        {
            if (_progressText != value)
            {
                _progressText = value;
                OnPropertyChanged();
            }
        }
    }

    public string ProgressDetailText
    {
        get => _progressDetailText;
        set
        {
            if (_progressDetailText != value)
            {
                _progressDetailText = value;
                OnPropertyChanged();
            }
        }
    }

    public double ProgressPercentage
    {
        get => _progressPercentage;
        set
        {
            if (Math.Abs(_progressPercentage - value) > 0.01)
            {
                _progressPercentage = value;
                OnPropertyChanged();
            }
        }
    }

    public bool IsProgressIndeterminate
    {
        get => _isProgressIndeterminate;
        set
        {
            if (_isProgressIndeterminate != value)
            {
                _isProgressIndeterminate = value;
                OnPropertyChanged();
            }
        }
    }

    static UpdateProgressDialog()
    {
        DefaultStyleKeyProperty.OverrideMetadata(
            typeof(UpdateProgressDialog),
            new FrameworkPropertyMetadata(typeof(ContentDialog))
        );
    }

    public UpdateProgressDialog()
    {
        InitializeComponent();
        DialogHelper.SetupDialogHost(this);

        if (Application.Current.TryFindResource(typeof(ContentDialog)) is Style dialogStyle)
            Style = dialogStyle;
            
        DataContext = this;

        DialogHelper.HideActionButtonsArea(this);

        Closing += (s, e) =>
        {
            if (!IsProgrammaticClose)
                e.Cancel = true;
        };
    }

    public bool IsProgrammaticClose { get; set; } = false;

    public void CloseDialog()
    {
        IsProgrammaticClose = true;
        this.Hide();
    }

    protected void OnPropertyChanged([CallerMemberName] string? name = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
