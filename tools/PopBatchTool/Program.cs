using System.Reflection;
using System.Text;
using QinBan.Core;

Console.OutputEncoding = Encoding.UTF8;
try
{
    if (args is ["build", var buildManifest, var baseline, var output])
    {
        var report = BuildRunner.Build(buildManifest, baseline, output, syntheticFixture: false);
        Console.WriteLine($"{report.Status}: {report.Songs.Count} MIDI; {report.Mappings.Count} mappings; {report.Waves.Count} fragment WAVs; {output}");
    }
    else if (args is ["restart-check", var songs, var data, var expected, var restartOutput])
        Files.JsonNew(restartOutput, BuildRunner.VerifyStore(songs, data, Files.Read<List<LibraryEntry>>(expected)));
    else if (args is ["validate-manifest", var validateManifest])
        Console.WriteLine(Files.Json(BuildRunner.ValidateManifestOnly(validateManifest)));
    else
    {
        Console.WriteLine("PopBatchTool (GPL-3.0) - generic local structured-MIDI conversion and numerical checks; no music or rights certification, no playback, no real input.\n"
            + "build <manifest.json> <existing-baseline-Songs-dir> <NEW-output-dir>\n"
            + "validate-manifest <manifest.json>\n"
            + "build accepts a provider-declared source-MIDI batch plus an existing catalog baseline; output must not already exist.");
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
