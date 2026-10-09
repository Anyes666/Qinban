namespace AutoMidiPlayer.WPF.Core.Instruments;

/// <summary>
/// Wuthering Waves 21-key QWERTY layout.
/// The three seven-note rows are ordered as displayed in game: high, middle, then low.
/// </summary>
internal static class WutheringWavesKeyboardLayouts
{
    public static readonly KeyboardLayoutConfig QWERTY = new(
        name: "QWERTY",
        keys:
        [
            "q", "w", "e", "r", "t", "y", "u",
            "a", "s", "d", "f", "g", "h", "j",
            "z", "x", "c", "v", "b", "n", "m",
        ]);
}
