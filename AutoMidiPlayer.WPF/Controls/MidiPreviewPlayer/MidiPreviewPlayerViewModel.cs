using System;
using System.Windows.Threading;
using AutoMidiPlayer.WPF.Services.MidiShow;
using Melanchall.DryWetMidi.Multimedia;
using Stylet;

namespace AutoMidiPlayer.WPF.Controls.MidiPreviewPlayer;

public class MidiPreviewPlayerViewModel : PropertyChangedBase
{
    private readonly MidiShowPreviewPlayer _preview = new();
    private DispatcherTimer? _previewTimer;

    public MidiPreviewPlayerViewModel()
    {
        _preview.Finished += OnPreviewFinished;
    }

    private void OnPreviewFinished()
    {
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
            Stop();
        else
            dispatcher.Invoke(Stop);
    }

    public bool IsPreviewActive { get; private set; }

    public bool IsPreviewPlaying { get; private set; }

    public string PreviewTitle { get; private set; } = string.Empty;
    public string PreviewUploader { get; private set; } = string.Empty;
    public string PreviewAvatarUrl { get; private set; } = string.Empty;
    public bool HasPreviewAvatar => !string.IsNullOrEmpty(PreviewAvatarUrl);
    public bool HasPreviewUploader => !string.IsNullOrEmpty(PreviewUploader);

    public double PreviewDurationSeconds { get; private set; }
    private double _previewPositionSeconds;
    public double PreviewPositionSeconds
    {
        get => _previewPositionSeconds;
        set
        {
            _previewPositionSeconds = value;
            NotifyOfPropertyChange(nameof(PreviewPositionSeconds));
            
            PreviewPositionText = FormatTime(TimeSpan.FromSeconds(value));
            NotifyOfPropertyChange(nameof(PreviewPositionText));
            
            if (!IsPreviewScrubbing)
            {
                DisplayPreviewPositionSeconds = value;
            }
        }
    }

    private double _displayPreviewPositionSeconds;
    public double DisplayPreviewPositionSeconds
    {
        get => _displayPreviewPositionSeconds;
        set
        {
            _displayPreviewPositionSeconds = value;
            NotifyOfPropertyChange(nameof(DisplayPreviewPositionSeconds));
        }
    }
    
    private bool _isPreviewScrubbing;
    public bool IsPreviewScrubbing
    {
        get => _isPreviewScrubbing;
        set
        {
            if (_isPreviewScrubbing == value) return;
            _isPreviewScrubbing = value;
            NotifyOfPropertyChange(nameof(IsPreviewScrubbing));

            if (!value)
            {
                DisplayPreviewPositionSeconds = PreviewPositionSeconds;
                _preview.Seek(TimeSpan.FromSeconds(PreviewPositionSeconds));
            }
        }
    }

    public string PreviewPositionText { get; private set; } = "0:00";
    public string PreviewDurationText { get; private set; } = "0:00";

    public void Play(byte[] data, string title, string? uploader, string? avatarUrl, OutputDevice synth)
    {
        _preview.Play(data, synth);

        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is not null && !dispatcher.CheckAccess())
        {
            dispatcher.Invoke(() => UpdatePropertiesAndTimer(title, uploader, avatarUrl));
        }
        else
        {
            UpdatePropertiesAndTimer(title, uploader, avatarUrl);
        }
    }

    private void UpdatePropertiesAndTimer(string title, string? uploader, string? avatarUrl)
    {
        PreviewTitle = title;
        PreviewUploader = uploader ?? string.Empty;
        PreviewAvatarUrl = avatarUrl ?? string.Empty;
        IsPreviewActive = true;
        IsPreviewPlaying = true;
        
        PreviewDurationSeconds = Math.Max(0.1, _preview.Duration.TotalSeconds);
        PreviewPositionSeconds = 0;
        PreviewDurationText = FormatTime(_preview.Duration);

        NotifyOfPropertyChange(nameof(PreviewTitle));
        NotifyOfPropertyChange(nameof(PreviewUploader));
        NotifyOfPropertyChange(nameof(PreviewAvatarUrl));
        NotifyOfPropertyChange(nameof(HasPreviewAvatar));
        NotifyOfPropertyChange(nameof(HasPreviewUploader));
        NotifyOfPropertyChange(nameof(IsPreviewActive));
        NotifyOfPropertyChange(nameof(IsPreviewPlaying));
        NotifyOfPropertyChange(nameof(PreviewDurationSeconds));
        NotifyOfPropertyChange(nameof(PreviewDurationText));

        StartPreviewTimer();
    }

    public void TogglePlayPause()
    {
        if (!IsPreviewActive)
            return;

        _preview.TogglePlayPause();
        IsPreviewPlaying = _preview.IsPlaying;
        NotifyOfPropertyChange(nameof(IsPreviewPlaying));
    }

    public void Stop()
    {
        StopPreviewTimer();
        _preview.Stop();
        IsPreviewActive = false;
        IsPreviewPlaying = false;
        PreviewPositionSeconds = 0;
        
        NotifyOfPropertyChange(nameof(IsPreviewActive));
        NotifyOfPropertyChange(nameof(IsPreviewPlaying));
        NotifyOfPropertyChange(nameof(PreviewPositionSeconds));
    }

    private void StartPreviewTimer()
    {
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is not null && !dispatcher.CheckAccess())
        {
            dispatcher.Invoke(StartPreviewTimer);
            return;
        }

        if (_previewTimer is null)
        {
            _previewTimer = new DispatcherTimer
            {
                Interval = TimeSpan.FromMilliseconds(250)
            };
            _previewTimer.Tick += (_, _) => OnPreviewTick();
        }
        _previewTimer.Start();
    }

    private void StopPreviewTimer()
    {
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is not null && !dispatcher.CheckAccess())
        {
            dispatcher.Invoke(StopPreviewTimer);
            return;
        }

        _previewTimer?.Stop();
    }

    private void OnPreviewTick()
    {
        if (!IsPreviewActive)
            return;

        var playing = _preview.IsPlaying;
        if (playing != IsPreviewPlaying)
        {
            IsPreviewPlaying = playing;
            NotifyOfPropertyChange(nameof(IsPreviewPlaying));
        }

        if (IsPreviewScrubbing)
            return;

        var pos = _preview.CurrentTime;
        PreviewPositionSeconds = pos.TotalSeconds;
    }

    private static string FormatTime(TimeSpan time)
    {
        return time.TotalHours >= 1
            ? $"{(int)time.TotalHours}:{time.Minutes:D2}:{time.Seconds:D2}"
            : $"{time.Minutes}:{time.Seconds:D2}";
    }
}
