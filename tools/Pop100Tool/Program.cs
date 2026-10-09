using System.Reflection;
using System.Text;
using QinBan.Core;

Console.OutputEncoding = Encoding.UTF8;
try
{
    if (args is ["build", var manifest, var baseline, var output])
    {
        var report = BuildRunner.Build(manifest, baseline, output, syntheticFixture: false);
        Console.WriteLine($"{report.Status}: {report.Songs.Count} MIDI; {report.Mappings.Count} mappings; {report.Waves.Count} fragment WAVs; {output}");
    }
    else if (args is ["self-test", var selfOutput]) SelfTest.Run(selfOutput);
    else if (args is ["restart-check", var songs, var data, var expected, var restartOutput])
        Files.JsonNew(restartOutput, BuildRunner.VerifyStore(songs, data, Files.Read<List<LibraryEntry>>(expected)));
    else
    {
        Console.WriteLine("Pop100Tool (GPL-3.0) — 本地转换/数值测试，不认证音乐与再分发，不播放/不发送按键。\n"
            + "build <manifest.json> <existing-baseline-Songs-dir> <NEW-output-dir>\n"
            + "self-test <NEW-directory-under-tools/Pop100Tool>\n"
            + "build 要求 100 首 MIDI + 32 条基线 catalog；已存在 output 一律拒绝。");
        return args.Length == 0 || args is ["--help"] ? 0 : 2;
    }
    return 0;
}
catch (Exception ex) { Console.Error.WriteLine(ex.ToString()); return 1; }

internal static class ToolLocation
{
    public static string Root => Assembly.GetExecutingAssembly().GetCustomAttributes<AssemblyMetadataAttribute>()
        .Single(a => a.Key == "ToolRoot").Value!;
}
