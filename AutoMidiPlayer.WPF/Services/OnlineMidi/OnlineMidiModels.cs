using System;
using System.Collections.Generic;
using System.Linq;
using Stylet;

namespace AutoMidiPlayer.WPF.Services.OnlineMidi;

public record OnlineMidiPageResult(IReadOnlyList<OnlineMidiItem> Items, string StatusText);

public class FilterOption
{
    public string Key { get; }
    public string Name { get; }
    public string Icon { get; }

    public FilterOption(string key, string name, string icon = "")
    {
        Key = key;
        Name = name;
        Icon = icon;
    }
}

/// <summary>
/// A single MIDI entry parsed from a MidiShow list or search results page.
/// </summary>
public sealed class OnlineMidiItem : PropertyChangedBase
{
    /// <summary>Numeric MidiShow id (from the <c>data-key</c> attribute).</summary>
    public string Id { get; init; } = string.Empty;

    public bool ProviderSupportsTags { get; init; } = true;

    private bool _isLoading;
    /// <summary>Indicates if this item is a loading skeleton.</summary>
    public bool IsLoading
    {
        get => _isLoading;
        set
        {
            if (SetAndNotify(ref _isLoading, value))
            {
                NotifyOfPropertyChange(nameof(HasCategoryOrTags));
            }
        }
    }

    /// <summary>Absolute URL of the MIDI detail page (used to download).</summary>
    public string PageUrl { get; init; } = string.Empty;

    /// <summary>Display title of the track.</summary>
    public string Title { get; init; } = string.Empty;

    /// <summary>Uploader / author username, when available.</summary>
    public string? Uploader { get; init; }

    /// <summary>Avatar/thumbnail image URL, when available.</summary>
    public string? ThumbnailUrl { get; init; }

    /// <summary>MIDI standard label (e.g. "GM1"), when available.</summary>
    public string? Standard { get; init; }

    /// <summary>Track duration, e.g. "02:55" (string, "" when unknown).</summary>
    public string Duration { get; init; } = "";

    /// <summary>Download count, e.g. "720" (number as string, "0" when unknown).</summary>
    public string Downloads { get; init; } = "0";

    /// <summary>Number of tracks ("0" when unknown).</summary>
    public string TrackCount { get; init; } = "0";

    /// <summary>Music category, e.g. "Anime/Game music" ("" when unknown).</summary>
    public string Category { get; init; } = "";

    /// <summary>Tags joined for display, e.g. "your name · sparkle" ("" when none).</summary>
    public string Tags { get; init; } = "";

    /// <summary>The individual tags as a list for rendering separate chips.</summary>
    public IReadOnlyList<string> TagsList { get; init; } = Array.Empty<string>();

    /// <summary>Short description / introduction snippet ("" when none).</summary>
    public string Description { get; init; } = "";

    /// <summary>Average rating, e.g. "5.0" ("0.0" when unrated).</summary>
    public string Rating { get; init; } = "0.0";

    /// <summary>Number of ratings ("0" when none).</summary>
    public string RatingCount { get; init; } = "0";

    private string? _bpm;
    public string? Bpm
    {
        get => _bpm;
        set
        {
            if (SetAndNotify(ref _bpm, value))
            {
                NotifyOfPropertyChange(nameof(HasBpm));
                NotifyOfPropertyChange(nameof(IsBpmSectionVisible));
            }
        }
    }
    public string Views { get; init; } = "0";
    public string? Arranger { get; init; }

    public bool HasStandard => !string.IsNullOrEmpty(Standard);
    public bool HasThumbnail => !string.IsNullOrEmpty(ThumbnailUrl);
    public bool HasDuration => !string.IsNullOrEmpty(Duration);
    public bool HasBpm => Bpm is not (null or "" or "0");
    public bool HasDownloads => Downloads is not (null or "" or "0");
    public bool HasViews => Views is not (null or "" or "0");
    
    public bool HasTrackCount => TrackCount is not (null or "" or "0");
    public bool HasCategory => !string.IsNullOrEmpty(Category);
    public bool HasTags => !string.IsNullOrEmpty(Tags);
    public bool HasCategoryOrTags => ProviderSupportsTags && (HasCategory || HasTags || IsLoading);
    public bool HasDescription => !string.IsNullOrEmpty(Description);
    public bool HasRating => RatingCount is not (null or "" or "0");
    

    public string? InstrumentCount { get; init; }
    public bool HasInstrumentCount => InstrumentCount is not (null or "" or "0");

    public string? FileSize { get; init; }
    public bool HasFileSize => !string.IsNullOrEmpty(FileSize);

    public string? UploadDate { get; init; }
    public bool HasUploadDate => !string.IsNullOrEmpty(UploadDate);

    public string? UploadDateDisplay => string.IsNullOrEmpty(UploadDate) ? null : 
        (DateTime.TryParse(UploadDate, out var dt) ? dt.ToString("MM/dd/yyyy") : UploadDate);

    public string? UploadDateTooltip => string.IsNullOrEmpty(UploadDate) ? null :
        (DateTime.TryParse(UploadDate, out var dt) ? $"Uploaded on {dt:MMMM d, yyyy}" : $"Uploaded on {UploadDate}");

    public string TrackCountTooltip => (TrackCount == "1") ? "1 Track" : $"{TrackCount} Tracks";
    public string InstrumentCountTooltip => (InstrumentCount == "1") ? "1 Instrument" : $"{InstrumentCount} Instruments";
    
    public string RatingTooltip
    {
        get
        {
            if (string.IsNullOrEmpty(Rating) || Rating == "0.0") return "Unrated";
            var people = RatingCount == "1" ? "1 person" : $"{RatingCount} people";
            return $"Rated {Rating} stars by {people}";
        }
    }
    
    public string DurationTooltip => $"Duration: {Duration}";
    public string UploaderTooltip => $"By {Uploader}";
    public string FileSizeTooltip => $"File Size: {FileSize}";

    /// <summary>Rating shown as "5.0 (8)".</summary>
    public string RatingDisplay => $"{Rating} ({RatingCount})";

    private bool _isPreviewPlaying;
    public bool IsPreviewPlaying
    {
        get => _isPreviewPlaying;
        set => SetAndNotify(ref _isPreviewPlaying, value);
    }

    private bool _isExpanded;
    public bool IsExpanded
    {
        get => _isExpanded;
        set => SetAndNotify(ref _isExpanded, value);
    }

    private bool _isLoadingDetails;
    public bool IsLoadingDetails
    {
        get => _isLoadingDetails;
        set
        {
            if (SetAndNotify(ref _isLoadingDetails, value))
                NotifyOfPropertyChange(nameof(IsBpmSectionVisible));
        }
    }

    private MidiShowDetails? _details;
    public MidiShowDetails? Details
    {
        get => _details;
        set
        {
            if (SetAndNotify(ref _details, value))
            {
                if (_details?.HasBpm == true) Bpm = _details.Bpm;
                NotifyOfPropertyChange(nameof(IsBpmSectionVisible));
            }
        }
    }

    public bool IsBpmSectionVisible => IsLoadingDetails || Details?.HasBpm == true || HasBpm;
}

/// <summary>
/// Full details for a single MIDI, parsed from its MidiShow detail page on demand.
/// </summary>
public sealed class MidiShowDetails
{
    public string Id { get; init; } = string.Empty;
    public string PageUrl { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string? Uploader { get; init; }
    public string? ThumbnailUrl { get; init; }
    public string? Standard { get; init; }

    public string? Duration { get; init; }
    public string? Bpm { get; init; }
    public string? TrackCount { get; init; }
    public string? NoteCount { get; init; }
    public string? FileSize { get; init; }
    public string? Instruments { get; init; }
    public string? Rating { get; init; }
    public string? Introduction { get; init; }
    public string Category { get; init; } = "";
    public string Tags { get; init; } = "";
    public string Downloads { get; init; } = "0";

    public bool HasThumbnail => !string.IsNullOrEmpty(ThumbnailUrl);
    public bool HasStandard => !string.IsNullOrEmpty(Standard);
    public bool HasDuration => !string.IsNullOrEmpty(Duration);
    public bool HasBpm => Bpm is not (null or "" or "0");
    public bool HasTrackCount => TrackCount is not (null or "" or "0");
    public bool HasNoteCount => NoteCount is not (null or "" or "0");
    public bool HasFileSize => !string.IsNullOrEmpty(FileSize);
    public bool HasInstruments => !string.IsNullOrEmpty(Instruments);
    public bool HasRating => !string.IsNullOrEmpty(Rating);
    public bool HasIntroduction => !string.IsNullOrEmpty(Introduction);
    public bool HasCategory => !string.IsNullOrEmpty(Category);
    public bool HasTags => !string.IsNullOrEmpty(Tags);
    public bool HasDownloads => Downloads is not (null or "" or "0");

    public IReadOnlyList<MidiShowTrack> Tracks { get; init; } = Array.Empty<MidiShowTrack>();
    public bool HasTracks => Tracks.Count > 0;
}

public sealed class MidiShowTrack
{
    public string Number { get; set; } = "";
    public string Name { get; set; } = "";
    public string Channel { get; set; } = "";
    public string Instrument { get; set; } = "";
    public string ProgramId { get; set; } = "";
    public string NotesCount { get; set; } = "";
}

/// <summary>
/// Result of a download attempt: the raw MIDI bytes and a suggested title.
/// </summary>
public sealed record MidiShowDownloadResult(byte[] Data, string Title, System.Collections.Generic.Dictionary<int, string>? TrackNames = null);

/// <summary>
/// Reasons a download may fail, surfaced to the UI for a friendly message.
/// </summary>
public enum MidiShowDownloadError
{
    None,
    NotAuthenticated,
    NotFound,
    Network,
    Decode,

    NotActivated,

    /// <summary>
    /// The account's per-day download quota / points balance / VIP requirement blocked the
    /// download. The session is still valid; it's a quota issue, not an auth failure.
    /// </summary>
    LimitReached,

    /// <summary>
    /// MidiShow flagged this account's activity as abnormal (risk control / too frequent).
    /// The credentials are valid but this account is temporarily blocked from downloading;
    /// the right fix is to use a different account or wait. Surfaced separately so the pool
    /// can rotate to another account instead of treating it as a sign-in failure.
    /// </summary>
    RiskControlled
}

/// <summary>
/// Thrown by <see cref="MidiShowClient"/> when an operation cannot complete.
/// </summary>
public sealed class MidiShowException : System.Exception
{
    public MidiShowDownloadError Reason { get; }

    public MidiShowException(MidiShowDownloadError reason, string message, System.Exception? inner = null)
        : base(message, inner)
    {
        Reason = reason;
    }
}

/// <summary>Lifecycle/health of one account in the pool, for display.</summary>
public enum MidiShowAccountState
{
    /// <summary>Configured but not signed in yet.</summary>
    Idle,
    SigningIn,
    /// <summary>Signed in and usable for downloads.</summary>
    Active,
    /// <summary>Hit a download quota / points / VIP wall — cooling down.</summary>
    Limited,
    /// <summary>Flagged by MidiShow risk control — cooling down.</summary>
    RiskControlled,
    /// <summary>Sign-in failed (bad password / expired cookies).</summary>
    AuthFailed,
    /// <summary>Email needs verification.</summary>
    NotActivated
}

/// <summary>A read-only snapshot of one account's identity and current health.</summary>
public sealed record MidiShowAccountStatus(string Username, bool IsCookieBased, MidiShowAccountState State);
