namespace AutoMidiPlayer.WPF.Core.Instruments;

/// <summary>
/// Wuthering Waves playable instruments.
/// </summary>
public static partial class WutheringWavesInstruments
{
    /// <summary>
    /// The two tested instruments share this 21-key, three-row diatonic layout and are
    /// represented by one config because their controls are identical.
    /// </summary>
    public static readonly InstrumentConfig Instrument21Key = new(
        game: "Wuthering Waves",
        name: "21-Key Instrument",
        notes:
        [
            72, 74, 76, 77, 79, 81, 83, // C5 D5 E5 F5 G5 A5 B5
            60, 62, 64, 65, 67, 69, 71, // C4 D4 E4 F4 G4 A4 B4
            48, 50, 52, 53, 55, 57, 59, // C3 D3 E3 F3 G3 A3 B3
        ],
        keyboardLayouts: [WutheringWavesKeyboardLayouts.QWERTY]);
}
