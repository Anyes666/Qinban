using System.Collections.Generic;

namespace AutoMidiPlayer.WPF.Core.Instruments
{
    public static partial class CoreKeeperInstruments
    {
        public static readonly InstrumentConfig Ocarina = new(
            game: "Core Keeper",
            name: "Ocarina",
            notes: [
                84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, // C6  C#6 D6  D#6 E6  F6  F#6 G6  G#6 A6  A#6 B6
                72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, // C5  C#5 D5  D#5 E5  F5  F#5 G5  G#5 A5  A#5 B5
            ],
            keyboardLayouts: [
                CoreKeeperKeyboardLayouts.QWERTY
            ]
        );
    }
}
