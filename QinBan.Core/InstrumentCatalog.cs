namespace QinBan.Core;

// Data transcription, not code copied from the reference projects.
// Source snapshot and uncertainty boundaries: INSTRUMENTS.md / tools/instrument-assets.json.
public sealed record InstrumentKey(char Key, string Label, IReadOnlyList<int> Pitches)
{
    public bool IsChord => Pitches.Count > 1;
}
public sealed record InstrumentProfile(string Id, string Name, string? IconFile, string Layout,
    bool SupportsSustain, bool CanAutoPlay, IReadOnlyList<InstrumentKey> Keys, string Note)
{
    public IReadOnlyList<InstrumentKey> MelodyKeys => Keys.Where(k => !k.IsChord).ToArray();
}
public static class InstrumentCatalog
{
    private static readonly int[] Scale = [0, 2, 4, 5, 7, 9, 11];
    private static InstrumentKey[] Rows(string keys, params int[] bases) => keys.Select((k, i) =>
        new InstrumentKey(k, GameMapping.NoteName(bases[i / 7] + Scale[i % 7]), new[] { bases[i / 7] + Scale[i % 7] })).ToArray();
    private static InstrumentProfile Standard(string id, string name, bool sustain, string? icon = null) =>
        new(id, name, icon ?? id + ".png", "21 键 · C3–B5", sustain, true, Rows(GameMapping.Keys, 72, 60, 48),
            sustain ? "按谱保持长短音；实际音尾由游戏决定。" : "保留谱面节奏与休止；拨弦音尾由游戏采样决定，长按不等于延音。");
    private static InstrumentProfile Guitar(string id, string name, int lower) => new(id, name, id + ".png",
        $"14 单音 + 7 和弦 · {GameMapping.NoteName(lower)}–{GameMapping.NoteName(lower + 23)}", false, true,
        ChordKeys(lower + 12).Concat(Rows("ASDFGHJZXCVBNM", lower + 12, lower)).ToArray(),
        "Q–U 为 C / Dm / Em / F / G / Am / G7；仅将原谱已有的同拍完整和弦匹配为和弦键，绝不把高音旋律当和弦。未匹配音符折叠到下两排。");
    private static InstrumentKey[] ChordKeys(int root) =>
    [
        new('Q', "C", new[] { root, root + 4, root + 7 }),
        new('W', "Dm", new[] { root + 2, root + 5, root + 9 }),
        new('E', "Em", new[] { root + 4, root + 7, root + 11 }),
        new('R', "F", new[] { root + 5, root + 9, root + 12 }),
        new('T', "G", new[] { root + 7, root + 11, root + 14 }),
        new('Y', "Am", new[] { root + 9, root + 12, root + 16 }),
        new('U', "G7", new[] { root + 7, root + 11, root + 14, root + 17 })
    ];
    public static IReadOnlyList<InstrumentProfile> All { get; } =
    [
        Standard("windsong", "风物之诗琴", false),
        Standard("floral", "镜花之琴", false),
        new("vintage", "老旧的诗琴", "vintage.png", "21 键 · 特殊调式", false, true,
            GameMapping.Keys.Select((k, i) => { int[] p = [72, 73, 75, 77, 79, 80, 82, 60, 62, 63, 65, 67, 69, 70, 48, 50, 51, 53, 55, 57, 58]; return new InstrumentKey(k, GameMapping.NoteName(p[i]), new[] { p[i] }); }).ToArray(),
            "各音区含不同降音，不沿用风物诗琴的自然音映射；半音适配以此乐器的实际音高表为准。"),
        new("horn", "晚风圆号", "horn.png", "14 键 · C3–B4", true, true, Rows("QWERTYUASDFGHJ", 60, 48),
            "Q–U 高排 / A–J 低排；超出两八度按所选音域策略折叠或跳过。请先与游戏键位核对。"),
        Guitar("ukulele", "悠可琴", 60),
        Guitar("euphonia", "「余音」", 48),
        // The data source has a profile, but no verified item artwork was retrievable.
        Standard("piano", "跃律琴", true) with { IconFile = null, Note = "资料音高表为标准 21 键；尚未取得可核验的道具图标，也未完成游戏内核验。" },
        Standard("harmonic", "谐律键琴", true),
        new("voice", "声线演奏（角色能力）", "voice.png", "14 键 · C4–B5", true, true, Rows("QWERTYUASDFGHJ", 72, 60),
            "额外提供截图中的 14 键声线布局；头像不是独立乐器道具图标。角色能力音域依据社区测音表，需游戏内核对。"),
        UnverifiedDrum("arataki", "荒泷·盛世豪鼓"),
        UnverifiedDrum("qiyan", "绮筵之鼓"),
        UnverifiedDrum("djem", "聚聚鼓")
    ];
    private static InstrumentProfile UnverifiedDrum(string id, string name) => new(id, name, id + ".png",
        "打击乐 · 键位待核验", false, false, [], "鼓类没有可还原旋律的固定音高；当前游戏键位待核验，暂不生成按键计划，不把旋律强行转换成鼓点。");
    public static InstrumentProfile Get(string id) => All.FirstOrDefault(p => p.Id == id)
        ?? throw new FormatException($"未知乐器配置：{id}");
}
