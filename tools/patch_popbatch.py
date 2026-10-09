from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'tools'/'PopBatchTool'/'BuildRunner.cs'
s=path.read_text(encoding='utf-8')
s=s.replace('// 200-song additive batch; based on the proven Pop200Tool without modifying it.', '// Generic additive source batch; based on the proven Pop200Tool without modifying it.')
s=s.replace('Files.Require(!syntheticFixture, "本批次工具不允许合成谱绕过真实200首准入");', 'Files.Require(!syntheticFixture, "本批次工具不允许合成谱绕过真实来源准入");')
s=s.replace('.pop200-output-owner', '.popbatch-output-owner')
s=s.replace('''                song.Provenance = new() {
                    WorkId = "pop909:" + input.Id, EditionId = "pop909:" + manifest.SourceCommit + ":" + input.Id,
                    Artist = input.Artist, Artists = [input.Artist], LanguageTags = [.. input.LanguageTags], Provider = "POP909",
                    SourceUrl = input.SourceUrl, SourceSha256 = input.SourceSha256, RetrievedAt = manifest.RetrievedAtUtc,
                    License = LicenseDeclaration, Completeness = "unknown", TimingStatus = "unverified",
                    MusicReview = "not-reviewed", GameReview = "not-tested", RedistributionVerified = false, Synthetic = syntheticFixture
                };''', '''                Files.Require(!string.IsNullOrWhiteSpace(input.WorkId) && !string.IsNullOrWhiteSpace(input.EditionId), "版本谱必须有WorkId和EditionId: " + input.Id);
                song.Provenance = new() {
                    WorkId = input.WorkId, EditionId = input.EditionId,
                    Artist = input.Artist, Artists = input.Artists is { Count: > 0 } ? [.. input.Artists] : [input.Artist],
                    LanguageTags = [.. input.LanguageTags], Album = input.Album, VersionLabel = input.VersionLabel,
                    Provider = string.IsNullOrWhiteSpace(manifest.Provider) ? "POP909" : manifest.Provider,
                    Aliases = [.. input.Aliases], Tags = [.. input.Tags],
                    SourceUrl = input.SourceUrl, SourceSha256 = input.SourceSha256, RetrievedAt = manifest.RetrievedAtUtc,
                    License = LicenseDeclaration, Completeness = input.Completeness, TimingStatus = "unverified",
                    MusicReview = input.MusicReview, GameReview = input.GameReview,
                    RedistributionVerified = input.RedistributionVerified, Synthetic = syntheticFixture
                };''')
s=s.replace('''            var entries = ReadBaseline(baseline, out var baselineMetadata);''', '''            var entries = ReadBaseline(baseline, out var baselineMetadata);
        var baselineEntries = entries.ToList();''')
s=s.replace('Files.Require(entries.Count == 332, "新曲库须为132旧条目+200新条目=332");', 'Files.Require(entries.Count == baselineEntries.Count + manifest.Songs.Count, "新曲库条目数必须等于基线+本批来源谱");')
s=s.replace('''        Files.Require(manifest.Songs != null && (fixture ? manifest.Songs.Count >= 5 && manifest.Songs.Count <= 10 : manifest.Songs.Count == 200), "生产build必须恰好200首；内部小夹具5至10首");''', '''        Files.Require(manifest.Songs != null && (fixture ? manifest.Songs.Count >= 1 && manifest.Songs.Count <= 10 : manifest.Songs.Count >= 1 && manifest.Songs.Count <= 5000), "生产build要求1至5000份真实来源谱；内部小夹具1至10份");''')
s=s.replace('string catalog = Path.Combine(root, LibraryCatalog.FileName); Files.Require(File.Exists(catalog), "必须提供已有132谱catalog.db，不可用fallback猜ID");', 'string catalog = Path.Combine(root, LibraryCatalog.FileName); Files.Require(File.Exists(catalog), "必须提供已有catalog.db，不可用fallback猜ID");')
s=s.replace('''        Files.Require(result.Count == 132 && result.Select(e => e.RelativePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 132
            && result.Any(e => e.Id == "builtin:01.json"), "基线须恰好132谱/132独立资源并保留builtin:01.json");''', '''        Files.Require(result.Count > 0 && result.Select(e => e.RelativePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() == result.Count
            && result.Any(e => e.Id == "builtin:01.json"), "基线必须有独立资源并保留builtin:01.json");''')
s=s.replace('''                Files.Require(page.Total == 1 && page.Items.Single().Id == e.Id, "标题/歌手/组合搜索失败: " + e.Id + " / " + term);''', '''                Files.Require(page.Total > 0 && page.Items.Any(item => item.Id == e.Id), "标题/歌手/组合搜索未找到版本条目: " + e.Id + " / " + term);''')
s=s.replace('''            Files.Require(!e.Provenance.IsFormalSong && e.Provenance.TimingStatus == "source-compared"
                && e.Provenance.MusicReview == "not-reviewed" && e.Provenance.GameReview == "not-tested"
                && !e.Provenance.RedistributionVerified && e.Provenance.License == LicenseDeclaration
                && e.Options.Tracks is { Count: > 0 }, "POP provenance/default异常");''', '''            Files.Require(!e.Provenance.IsFormalSong && e.Provenance.TimingStatus == "source-compared"
                && e.Provenance.MusicReview == "not-reviewed" && e.Provenance.GameReview == "not-tested"
                && !e.Provenance.RedistributionVerified && e.Provenance.License == LicenseDeclaration
                && e.Options.Tracks is { Count: > 0 } && !string.IsNullOrWhiteSpace(e.Provenance.WorkId)
                && !string.IsNullOrWhiteSpace(e.Provenance.EditionId), "POP provenance/default异常");''')
path.write_text(s,encoding='utf-8')
prog=root/'tools'/'PopBatchTool'/'Program.cs'
p=prog.read_text(encoding='utf-8').replace('Pop200Tool','PopBatchTool').replace('200 首 MIDI + 132 条基线 catalog','任意批量 MIDI + 既有基线 catalog').replace('build 要求 200 首 MIDI + 132 条基线 catalog；已存在 output 一律拒绝。','build 要求真实来源 MIDI 批次 + 既有基线 catalog；已存在 output 一律拒绝。')
prog.write_text(p,encoding='utf-8')
print('patched PopBatchTool')
