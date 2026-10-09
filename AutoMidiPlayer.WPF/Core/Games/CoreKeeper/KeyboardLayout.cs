using System.Collections.Generic;

namespace AutoMidiPlayer.WPF.Core.Instruments
{
    /// <summary>
    /// Core Keeper keyboard layouts.
    /// All instruments share the same 24-key chromatic layout across 2 rows.
    /// The sounding range differs per instrument: Drumkit/Cello C2–B3, Harp/Pocket Piano C3–B4,
    /// Flute C4–B5, Ocarina C5–B6 — the top row plays the upper octave, the bottom row the lower.
    /// Top row:    q 2 w 3 e r 5 t 6 y 7 u
    /// Bottom row: z s x d c v g b h n j m
    /// </summary>
    internal static class CoreKeeperKeyboardLayouts
    {
        public static readonly KeyboardLayoutConfig QWERTY = new(
            name: "QWERTY",
            keys: [
                "q", "2", "w", "3", "e", "r", "5", "t", "6", "y", "7", "u",
                "z", "s", "x", "d", "c", "v", "g", "b", "h", "n", "j", "m",
            ]);
    }
}