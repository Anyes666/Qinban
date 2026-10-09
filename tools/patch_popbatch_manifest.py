from pathlib import Path
p=Path(__file__).resolve().parents[1]/'tools'/'PopBatchTool'/'BuildRunner.cs'
s=p.read_text(encoding='utf8')
old='            new ScoreProvenance { Artist = s.Artist, Artists = [s.Artist], LanguageTags = s.LanguageTags }.Validate();'
new='''            Files.Require(!string.IsNullOrWhiteSpace(s.WorkId) && !string.IsNullOrWhiteSpace(s.EditionId), "WorkId/EditionId不可缺失: " + s.Id);
            Files.Require(!s.RedistributionVerified && s.MusicReview == "not-reviewed" && s.GameReview == "not-tested", "未经审校/授权的来源状态被伪造: " + s.Id);
            var artists = s.Artists is { Count: > 0 } ? s.Artists : [s.Artist];
            new ScoreProvenance { WorkId = s.WorkId, EditionId = s.EditionId, Artist = s.Artist, Artists = [.. artists],
                LanguageTags = s.LanguageTags, Album = s.Album, VersionLabel = s.VersionLabel,
                Aliases = [.. s.Aliases], Tags = [.. s.Tags], Provider = string.IsNullOrWhiteSpace(manifest.Provider) ? "POP909" : manifest.Provider,
                SourceUrl = s.SourceUrl, SourceSha256 = s.SourceSha256, Completeness = s.Completeness,
                MusicReview = s.MusicReview, GameReview = s.GameReview, RedistributionVerified = s.RedistributionVerified }.Validate();'''
if old not in s: raise SystemExit('anchor not found')
p.write_text(s.replace(old,new),encoding='utf8')
print('manifest checks patched')
