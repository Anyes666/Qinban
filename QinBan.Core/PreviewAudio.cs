using System.Buffers.Binary;
using System.Runtime.InteropServices;

namespace QinBan.Core;

public static class PreviewAudio
{
    public const int SampleRate = 22050;
    public const double MaxPreviewMs = 10 * 60 * 1000;
    private const int BlockSampleCount = 32768;
    // One float mixing block plus one 16-bit PCM block; independent of song duration.
    // Score/chord metadata and small stream/header allocations are not sample buffers.
    public const int MaxSampleBufferBytes = BlockSampleCount * (sizeof(float) + sizeof(short));

    public static double WriteWave(PlaybackPlan plan, string path, CancellationToken token = default)
    {
        if (plan.Notes.Count == 0) throw new InvalidOperationException("没有可试听音符。");
        token.ThrowIfCancellationRequested();
        double duration = Math.Min(plan.DurationMs + 450, MaxPreviewMs);
        int length = checked((int)Math.Ceiling(duration * SampleRate / 1000));
        if (length < 0) throw new ArgumentOutOfRangeException(nameof(plan), "试听时长不能为负数。");
        string destination = Path.GetFullPath(path);
        if (File.Exists(destination) || Directory.Exists(destination))
            throw new IOException("试听目标已存在，不会覆盖：" + destination);
        string directory = Path.GetDirectoryName(destination)!;
        if (!Directory.Exists(directory)) throw new DirectoryNotFoundException(directory);
        string id = Guid.NewGuid().ToString("N");
        string floatPath = Path.Combine(directory, ".qinban-preview-" + id + ".float.tmp");
        string wavePath = Path.Combine(directory, ".qinban-preview-" + id + ".wav.tmp");
        bool waveCreated = false;
        try
        {
            // CreateNew establishes ownership. DeleteOnClose only removes this handle's UUID file,
            // including on cancellation/failure; no directory-wide or destination cleanup is used.
            using (var floats = new FileStream(floatPath, FileMode.CreateNew, FileAccess.ReadWrite,
                FileShare.None, 1, FileOptions.SequentialScan | FileOptions.DeleteOnClose))
            {
                var samples = new float[BlockSampleCount];
                var pcm = new byte[BlockSampleCount * sizeof(short)];
                float peak = length == 0 ? 1 : 0;
                for (int blockStart = 0; blockStart < length; blockStart += BlockSampleCount)
                {
                    token.ThrowIfCancellationRequested();
                    int blockLength = Math.Min(BlockSampleCount, length - blockStart);
                    Array.Clear(samples, 0, blockLength);
                    // Retain the original note-addition order and note-relative sample indices,
                    // so block boundaries cannot change float rounding, phase or the envelope.
                    foreach (var note in plan.Notes)
                    {
                        token.ThrowIfCancellationRequested();
                        if (!(note.StartMs < duration)) continue;
                        int start = (int)(note.StartMs * SampleRate / 1000);
                        if (start < 0) throw new ArgumentOutOfRangeException(nameof(plan), "音符起始时间不能为负数。");
                        int count = Math.Min((int)((note.SoundMs + 120) * SampleRate / 1000), length - start);
                        int first = Math.Max(0, blockStart - start);
                        int end = Math.Min(count, blockStart + blockLength - start);
                        if (first >= end) continue;
                        var pitches = note.ChordPitches ?? new[] { note.Pitch };
                        var frequencies = pitches.Select(pitch => 440 * Math.Pow(2, (pitch - 69) / 12.0)).ToArray();
                        double amplitude = .17 * note.Velocity / 127 / Math.Sqrt(pitches.Count);
                        double seconds = note.SoundMs / 1000;
                        for (int i = first; i < end; i++)
                        {
                            if (i % 16384 == 0) token.ThrowIfCancellationRequested();
                            double time = (double)i / SampleRate;
                            double attack = Math.Min(1, time / .005);
                            double release = time <= seconds ? 1 : Math.Max(0, 1 - (time - seconds) / .12);
                            // Score-aware synthetic envelope, not an imitation of the game's instrument samples.
                            double envelope = attack * release * (note.Sustain ? .85 : Math.Exp(-time * 2.5 / Math.Max(.08, seconds)));
                            double sample = 0;
                            foreach (double frequency in frequencies)
                            {
                                double phase = 2 * Math.PI * frequency * time;
                                sample += Math.Sin(phase) + .25 * Math.Sin(phase * 2) + .1 * Math.Sin(phase * 3);
                            }
                            samples[start + i - blockStart] += (float)(amplitude * envelope * sample);
                        }
                    }
                    for (int i = 0; i < blockLength; i++)
                    {
                        float magnitude = Math.Abs(samples[i]);
                        if (magnitude > peak) peak = magnitude;
                    }
                    token.ThrowIfCancellationRequested();
                    floats.Write(MemoryMarshal.AsBytes(samples.AsSpan(0, blockLength)));
                }
                // A single gain for the entire song, never per-block normalization/limiting.
                double gain = peak > .94 ? .94 / peak : 1;
                floats.Position = 0;
                token.ThrowIfCancellationRequested();
                using (var wave = new FileStream(wavePath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1))
                {
                    waveCreated = true;
                    using var output = new BinaryWriter(wave);
                    output.Write(System.Text.Encoding.ASCII.GetBytes("RIFF")); output.Write(36 + length * 2);
                    output.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt ")); output.Write(16); output.Write((short)1);
                    output.Write((short)1); output.Write(SampleRate); output.Write(SampleRate * 2); output.Write((short)2); output.Write((short)16);
                    output.Write(System.Text.Encoding.ASCII.GetBytes("data")); output.Write(length * 2);
                    for (int blockStart = 0; blockStart < length; blockStart += BlockSampleCount)
                    {
                        token.ThrowIfCancellationRequested();
                        int blockLength = Math.Min(BlockSampleCount, length - blockStart);
                        floats.ReadExactly(MemoryMarshal.AsBytes(samples.AsSpan(0, blockLength)));
                        for (int i = 0; i < blockLength; i++)
                        {
                            if (i % 16384 == 0) token.ThrowIfCancellationRequested();
                            short value = (short)Math.Clamp(samples[i] * gain * 32767, -32767, 32767);
                            BinaryPrimitives.WriteInt16LittleEndian(pcm.AsSpan(i * sizeof(short), sizeof(short)), value);
                        }
                        token.ThrowIfCancellationRequested();
                        output.Write(pcm, 0, blockLength * sizeof(short));
                    }
                }
            }
            // Both streams are closed (and the float file removed) before publication.
            // Same-directory rename is the commit point; a destination created meanwhile is retained.
            token.ThrowIfCancellationRequested();
            File.Move(wavePath, destination, overwrite: false);
            waveCreated = false;
            return duration;
        }
        finally
        {
            // Only delete the exact UUID WAV successfully created by this invocation, never path.
            // Cleanup errors propagate rather than silently claiming that cleanup succeeded.
            if (waveCreated) File.Delete(wavePath);
        }
    }
}