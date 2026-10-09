using System.Linq;
using Melanchall.DryWetMidi.Core;

namespace AutoMidiPlayer.Data.Midi.Extensions;

public static class MidiFileExtensions
{
    /// <summary>
    /// Removes NormalSysExEvents that contain an invalid first data byte (0xF0).
    /// DryWetMIDI's NormalSysExEvent constructor throws if Data[0] == 0xF0, 
    /// which causes Clone() and GetTimedEvents() to fail on malformed MIDI files.
    /// </summary>
    public static void RemoveMalformedSysExEvents(this Melanchall.DryWetMidi.Core.MidiFile midi)
    {
        foreach (var trackChunk in midi.GetTrackChunks())
        {
            var badEvents = trackChunk.Events
                .OfType<NormalSysExEvent>()
                .Where(e => e.Data?.Length > 0 && e.Data[0] == 240)
                .ToList();

            foreach (var bad in badEvents)
            {
                trackChunk.Events.Remove(bad);
            }
        }
    }
}
