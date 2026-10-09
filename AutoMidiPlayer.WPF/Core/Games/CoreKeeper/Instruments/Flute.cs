using System.Collections.Generic;

namespace AutoMidiPlayer.WPF.Core.Instruments
{
    public static partial class CoreKeeperInstruments
    {
        public static readonly InstrumentConfig Flute = new(
            game: "Core Keeper",
            name: "Flute",
            notes: [
                72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, // C5  C#5 D5  D#5 E5  F5  F#5 G5  G#5 A5  A#5 B5
                60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, // C4  C#4 D4  D#4 E4  F4  F#4 G4  G#4 A4  A#4 B4
            ],
            keyboardLayouts: [
                CoreKeeperKeyboardLayouts.QWERTY
            ]
        );
    }
}
