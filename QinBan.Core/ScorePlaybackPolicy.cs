namespace QinBan.Core;

public static class ScorePlaybackPolicy
{
    // A catalogue flag cannot be cleared simply by editing the loaded document, and vice versa.
    public static void EnsureRealInputAllowed(SongDocument song, LibraryEntry? entry = null)
    {
        if (song.Provenance.Synthetic || entry?.Provenance.Synthetic == true)
            throw new InvalidOperationException("合成压力条目仅供曲库测试，禁止向真实游戏输出；请选教学谱或已核验来源的个人谱。");
    }
}
