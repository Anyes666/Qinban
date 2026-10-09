from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'tools'/'PopBatchInterludeProbe'/'Program.cs'
s=p.read_text(encoding='utf8')
s=s.replace('// Additive200 stage-only matrix; old SmartInterludeProbe remains unchanged.', '// Generic stage-only batch matrix; old probes remain unchanged.')
s=s.replace('Path.Combine(ToolRoot,".validation","pop200-2026-10-06")','Path.Combine(ToolRoot,".validation","pop909-remaining-2026-10-06")')
s=s.replace('Only NEW direct matrix-* files are allowed:', 'Only NEW direct matrix-* files are allowed for this batch:')
s=s.replace('''        if(count!=332||ids.Count!=200||entries.Count!=200||entries.Select(e=>e.RelativePath).Distinct().Count()!=200)
            throw new InvalidOperationException("Expected catalogue332, exactly200 new manifest-bound POP909 entries");return entries;''', '''        if(count < ids.Count || ids.Count == 0 || entries.Count != ids.Count || entries.Select(e=>e.RelativePath).Distinct().Count()!=ids.Count)
            throw new InvalidOperationException("Expected every manifest-bound new POP909 entry in the stage catalogue");return entries;''')
s=s.replace('--matrix <passed-200-song-stage>', '--matrix <passed-batch-stage>')
s=s.replace('Only --matrix supported by the 200-song batch probe', 'Only --matrix supported by the batch probe')
s=s.replace('MATRIX {sourceEvidence.Count}/200:', 'MATRIX {sourceEvidence.Count}/{entries.Count}:')
s=s.replace('rows.Count==1800&&blocked.Count==600&&blockedBuilds==1800', 'rows.Count==entries.Count*9&&blocked.Count==entries.Count*3&&blockedBuilds==entries.Count*9')
s=s.replace('Expected 1800 off/on comparisons and 600 blocked drum combinations', 'Expected batchSize*9 off/on comparisons and batchSize*3 blocked drum combinations')
p.write_text(s,encoding='utf8')
cs=root/'tools'/'PopBatchInterludeProbe'/'PopBatchInterludeProbe.csproj'
c=cs.read_text(encoding='utf8').replace('Pop200InterludeProbe','PopBatchInterludeProbe').replace('Additive200','GenericBatch')
cs.write_text(c,encoding='utf8')
print('patched generic interlude probe')
