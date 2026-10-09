using QinBan.Core;
using System.Text.Json;
using System.Reflection;

internal sealed record Span(double StartMs,double EndMs) { public double LengthMs=>EndMs-StartMs; }
internal sealed record Failure(string Case,string Code,string Message,object? Details=null);
internal sealed class Audit(string name) {
    public string Name {get;}=name;
    public int Assertions {get;private set;}
    public List<Failure> Failures {get;}=[];
    public object? SlotProof {get;set;}
    public void Check(bool value,string code,string message,object? details=null) {
        Assertions++; if(!value) Failures.Add(new(Name,code,message,details));
    }
}
internal sealed record Oracle(List<NoteEvent> Basis,List<Span> Rests,List<Span> Occupied,List<Span> Slots,List<NoteEvent> Added,int Segments);
internal sealed record PlanStats(int Notes,double DurationMs,double? FirstOnsetMs,int InternalNoteOffGapsGe5s,
    double InternalNoteOffGapTotalMs,double MaxInternalNoteOffGapMs,double LeadingRestMs,double TrailingRestMs,
    int InternalOnsetGapsGe5s,double MaxOnsetGapMs,int NativeChords,List<Span> AllNoteOffRestsGe5s);
internal sealed record PairRow(string Case,string Id,string Instrument,string Scenario,double Speed,int Transpose,int Octave,
    List<int>? Tracks,int Assertions,int Failures,int BasisRawNotes,int OriginalRestsGe3s,int AddedSourceNotes,
    int AddedSourceBridgeNotes,int AddedSourcePianoNotes,int InterludeSegments,int AddedPlannedNotes,
    int SelectedKeyOnsets,int SelectedKeyOnsetsRetained,int SelectedNativeChords,int NativeChordChanges,
    int ChangedSelectedHoldOrSound,int ShortenedAddedSustainNotes,bool DefaultNullEqualsOn,
    PlanStats Off,PlanStats On,string OffOptionsHash,string OnOptionsHash);

internal static class Checks {
    internal const double Eps=0.000001;
    internal static bool Near(double a,double b)=>Math.Abs(a-b)<=Eps;
    internal static List<Span> Union(IEnumerable<Span> spans) {
        var list=new List<Span>();
        foreach(var x in spans.OrderBy(s=>s.StartMs).ThenBy(s=>s.EndMs)) {
            if(list.Count>0 && x.StartMs<=list[^1].EndMs) list[^1]=new(list[^1].StartMs,Math.Max(list[^1].EndMs,x.EndMs));
            else list.Add(x);
        }
        return list;
    }
    internal static List<Span> Rests(IEnumerable<Span> active,double start,double end) {
        var gaps=new List<Span>();double cursor=start;
        foreach(var x in Union(active)) {
            if(x.EndMs<=start||x.StartMs>=end) continue;
            if(x.StartMs>cursor) gaps.Add(new(cursor,Math.Min(x.StartMs,end)));
            cursor=Math.Max(cursor,Math.Min(x.EndMs,end));
        }
        if(cursor<end)gaps.Add(new(cursor,end));return gaps;
    }
    internal static Span RawSpan(NoteEvent n)=>new(n.StartMs,n.StartMs+n.DurationMs);
    internal static Span SoundSpan(PlannedNote n)=>new(n.StartMs,n.StartMs+n.SoundMs);
    internal static bool Overlap(Span a,Span b)=>a.StartMs<b.EndMs-Eps && b.StartMs<a.EndMs-Eps;
    // Deliberately independent, simple linear-scan oracle. It works only on raw score time,
    // then calls public GameMapping.Build with smart=false for established mapping behavior.
    internal static Oracle ArrangeOracle(SongDocument song,PlayOptions options) {
        var tracks=options.Tracks?.ToHashSet();
        var basis=song.Notes.Where(n=>(tracks==null||tracks.Contains(n.Track))&&(!options.ExcludePercussion||!n.Percussion)).ToList();
        var rests=Rests(basis.Select(RawSpan),0,song.DurationMs).Where(s=>s.LengthMs>=3000-Eps).ToList();
        var adds=new List<NoteEvent>();int segments=0;
        bool pop=string.Equals(song.Provenance.Provider,"POP909",StringComparison.OrdinalIgnoreCase);
        bool enabled=options.SmartInterludes??pop;
                var profile=InstrumentCatalog.Get(options.InstrumentId);
        var blocked=new List<Span>();
        foreach(var onset in basis.GroupBy(n=>n.StartMs)) {
            int delayedCount=options.Chords is ChordMode.Ascending or ChordMode.Descending?Math.Min(onset.Count(),options.MaxChordNotes)-1:0;
            double staggerRawMs=delayedCount*options.StrumMs*options.Speed;
            foreach(var note in onset) {
                double physicalHoldRawMs=options.HoldByScore&&profile.SupportsSustain?note.DurationMs:options.HoldMs*options.Speed;
                blocked.Add(new(note.StartMs,Math.Min(song.DurationMs,note.StartMs+Math.Max(note.DurationMs,physicalHoldRawMs)+staggerRawMs+8*options.Speed)));
            }
        }
        var occupied=Union(blocked);var free=Rests(occupied,0,song.DurationMs);
        // Raw eligibility and usable slot are distinct. Do not re-apply the 3s
        // threshold to narrowed slots. Cartesian interval intersections differ
        // from the Core's indexed intersection implementation.
        var slots=(from rest in rests from window in free
            let start=Math.Max(rest.StartMs,window.StartMs) let end=Math.Min(rest.EndMs,window.EndMs)
            where end>start select new Span(start,end)).OrderBy(s=>s.StartMs).ToList();
        if(!enabled||tracks==null||basis.Count==0)return new(basis,rests,occupied,slots,adds,0);
        var candidates=song.Notes.Where(n=>!tracks.Contains(n.Track)&&!n.Percussion).ToList();
        var ranks=candidates.GroupBy(n=>n.Track).OrderBy(g=>pop?g.Key:g.Count()).ThenBy(g=>g.Key)
            .Select((g,i)=>(g.Key,i)).ToDictionary(x=>x.Key,x=>x.i);
        void Fill(IEnumerable<NoteEvent> notes,Span window,List<NoteEvent> line) {
            double lastEnd=window.StartMs;
            foreach(var onset in notes.Where(n=>n.StartMs>=window.StartMs && n.StartMs<window.EndMs)
                .GroupBy(n=>n.StartMs).OrderBy(g=>g.Key)) {
                if(onset.Key<lastEnd)continue;
                var chosen=onset.Where(n=>n.StartMs+n.DurationMs<=window.EndMs)
                    .OrderBy(n=>ranks[n.Track]).ThenByDescending(n=>n.Pitch).ThenByDescending(n=>n.Velocity)
                    .ThenBy(n=>n.DurationMs).FirstOrDefault();
                if(chosen!=null) {line.Add(chosen);lastEnd=chosen.StartMs+chosen.DurationMs;}
            }
        }
        foreach(var rest in slots) {
            var line=new List<NoteEvent>();Fill(candidates.Where(n=>!pop||n.Track!=3),rest,line);
            if(pop) foreach(var space in Rests(line.Select(RawSpan),rest.StartMs,rest.EndMs).Where(s=>s.LengthMs>=1500-Eps))
                Fill(candidates.Where(n=>n.Track==3),space,line);
            if(line.Count>0){segments++;adds.AddRange(line);}
        }
        return new(basis,rests,occupied,slots,adds,segments);
    }
    internal static PlanStats Stats(PlaybackPlan p) {
        var union=Union(p.Notes.Select(SoundSpan));
        var internalGaps=union.Zip(union.Skip(1)).Select(x=>new Span(x.First.EndMs,x.Second.StartMs)).ToList();
        var starts=p.Notes.Select(n=>n.StartMs).Distinct().Order().ToArray();
        var onsetGaps=starts.Zip(starts.Skip(1)).Select(x=>x.Second-x.First).ToArray();
        return new(p.Notes.Count,p.DurationMs,starts.Length==0?null:starts[0],internalGaps.Count(g=>g.LengthMs>=5000-Eps),
            internalGaps.Where(g=>g.LengthMs>=5000-Eps).Sum(g=>g.LengthMs),internalGaps.Select(g=>g.LengthMs).DefaultIfEmpty(0).Max(),
            union.Count==0?p.DurationMs:union[0].StartMs,union.Count==0?0:Math.Max(0,p.DurationMs-union[^1].EndMs),
            onsetGaps.Count(g=>g>=5000-Eps),onsetGaps.DefaultIfEmpty(0).Max(),p.Report.NativeChords,
            Rests(p.Notes.Select(SoundSpan),0,p.DurationMs).Where(g=>g.LengthMs>=5000-Eps).ToList());
    }
    internal static string NoteFingerprint(PlannedNote n)=>Program.Serialize(n);
    internal static string KeyLabel((char Key,double StartMs) k)=>$"{k.Key}@{k.StartMs:R}";
    internal static (PairRow Row,PlaybackPlan Off,PlaybackPlan On,Oracle Oracle,Audit Audit) Pair(
        string id,string scenario,SongDocument song,PlayOptions baseOptions,string instrument,bool testNull=true) {
        string name=$"{scenario}/{id}/{instrument}";var audit=new Audit(name);
        string originalSong=Program.Serialize(song);var originalNotes=song.Notes.ToArray();
        string originalOptions=Program.Serialize(baseOptions);
        var offOptions=baseOptions.Copy();offOptions.InstrumentId=instrument;offOptions.SmartInterludes=false;
        var onOptions=offOptions.Copy();onOptions.SmartInterludes=true;
        string offState=Program.Serialize(offOptions),onState=Program.Serialize(onOptions);
        var off=GameMapping.Build(song,offOptions);
        audit.Check(originalSong==Program.Serialize(song)&&originalNotes.SequenceEqual(song.Notes),"SOURCE_MUTATED_OFF","Source mutated by explicit-off build");
        audit.Check(offState==Program.Serialize(offOptions),"STATE_MUTATED_OFF","Off options mutated");
        var on=GameMapping.Build(song,onOptions);
        audit.Check(originalSong==Program.Serialize(song)&&originalNotes.SequenceEqual(song.Notes),"SOURCE_MUTATED_ON","Source mutated by enabled build");
        audit.Check(onState==Program.Serialize(onOptions)&&originalOptions==Program.Serialize(baseOptions),"STATE_MUTATED_ON","Speed/transpose/octave/tracks or other options mutated");
        var oracle=ArrangeOracle(song,onOptions);
        var expectedSong=song.Copy();expectedSong.Notes=[..oracle.Basis,..oracle.Added];expectedSong.LengthMs=song.DurationMs;
        var expectedOptions=offOptions.Copy();expectedOptions.Tracks=null;
        var expected=GameMapping.Build(expectedSong,expectedOptions);
        bool samePlan=Program.Serialize(expected.Notes)==Program.Serialize(on.Notes)&&Near(expected.DurationMs,on.DurationMs);
        object? diff=samePlan?null:new {expectedAdded=oracle.Added.Count,actualReport=on.Report.InterludeNotes,expectedCount=expected.Notes.Count,actualCount=on.Notes.Count,
            expectedDuration=expected.DurationMs,actualDuration=on.DurationMs,expectedOnly=expected.Notes.Where(n=>!on.Notes.Any(x=>NoteFingerprint(x)==NoteFingerprint(n))).Take(5).ToList(),actualOnly=on.Notes.Where(n=>!expected.Notes.Any(x=>NoteFingerprint(x)==NoteFingerprint(n))).Take(5).ToList()};
        audit.Check(samePlan,"ARRANGEMENT_ORACLE_MISMATCH","Plan differs from independently selected raw-note handoff",diff);
        audit.Check(off.Report.InterludeNotes==0&&off.Report.InterludeSegments==0,"OFF_ADDS_NOTES","Explicit false must not add notes");
        audit.Check(on.Report.InterludeNotes==oracle.Added.Count&&on.Report.InterludeSegments==oracle.Segments,"REPORT_COUNTS","Report differs from independent source additions");
        var before=off.Notes.ToDictionary(n=>(n.Key,n.StartMs));var after=on.Notes.ToDictionary(n=>(n.Key,n.StartMs));
        var missing=before.Keys.Where(k=>!after.ContainsKey(k)).ToArray();
        audit.Check(missing.Length==0,"SELECTED_KEY_ONSETS_REMOVED","Selected original mapped key-onsets removed",missing.Take(12).Select(k=>new{k.Key,k.StartMs,original=before[k]}).ToArray());
        var identityChanges=before.Where(kv=>after.TryGetValue(kv.Key,out var n)&&
            (kv.Value.Track!=n.Track||kv.Value.Pitch!=n.Pitch||kv.Value.Velocity!=n.Velocity||kv.Value.Sustain!=n.Sustain||
             !(kv.Value.ChordPitches??[]).SequenceEqual(n.ChordPitches??[]))).ToArray();
        audit.Check(identityChanges.Length==0,"SELECTED_NATIVE_OR_IDENTITY_CHANGED","New tracks altered selected native-chord recognition or mapped identity",
            identityChanges.Take(12).Select(x=>new{old=x.Value,current=after[x.Key]}).ToArray());
        var nativeChanges=off.Notes.Where(n=>n.ChordPitches!=null).Where(n=>!after.TryGetValue((n.Key,n.StartMs),out var x)||
            x.ChordPitches==null||!n.ChordPitches!.SequenceEqual(x.ChordPitches)).ToList();
        audit.Check(nativeChanges.Count==0&&on.Report.NativeChords==off.Report.NativeChords,"NATIVE_CHORD_CHANGED","Existing native chords must not be changed or created by added tracks",new{off=off.Report.NativeChords,on=on.Report.NativeChords,nativeChanges});
        var addedPlan=on.Notes.Where(n=>!before.ContainsKey((n.Key,n.StartMs))).ToList();
        var selected=onOptions.Tracks?.ToHashSet();
        audit.Check(addedPlan.All(n=>selected!=null&&!selected.Contains(n.Track)&&n.ChordPitches==null),"ADDITION_NOT_UNSELECTED_MONOPHONIC","Added plan attacks must belong only to unselected tracks and not native chords");
        var badOrigins=addedPlan.Where(n=>!oracle.Added.Any(raw=>raw.Track==n.Track&&Near(raw.StartMs/onOptions.Speed,n.StartMs))).ToArray();
        audit.Check(badOrigins.Length==0,"ADDITION_SOURCE_ONSET_CHANGED","Added plan onset/track not found in allowed unselected original notes",badOrigins.Take(12).ToArray());
        audit.Check(oracle.Added.All(n=>song.Notes.Contains(n)&&!n.Percussion&&selected!=null&&!selected.Contains(n.Track)),"RAW_NOTE_IDENTITY","Added raw notes must be exact unselected non-percussion source records");
        var outside=oracle.Added.Where(n=>!oracle.Rests.Any(r=>n.StartMs>=r.StartMs&&n.StartMs+n.DurationMs<=r.EndMs&&r.LengthMs>=3000-Eps)).ToArray();
        audit.Check(outside.Length==0,"OUTSIDE_ORIGINAL_REST","Raw additions must fit entirely in an original >=3s basis note-off rest",outside.Take(12).ToArray());
        // Supplementary read-only raw-selection inspection: the primary tests still
        // exercise public GameMapping.Build. This independently establishes exact
        // original object/record identities and slots before mapping can clip sound.
        var method=typeof(SmartInterludeArranger).GetMethod("Arrange",BindingFlags.NonPublic|BindingFlags.Static)
            ??throw new InvalidOperationException("Raw arrangement diagnostic method not found");
        var selection=method.Invoke(null,[song,onOptions,CancellationToken.None])!;
        var actualRaw=((IEnumerable<NoteEvent>)selection.GetType().GetProperty("Notes")!.GetValue(selection)!).ToList();
        var actualAdded=actualRaw.Where(n=>selected!=null&&!selected.Contains(n.Track)).ToList();
        var actualBasis=actualRaw.Where(n=>selected==null||selected.Contains(n.Track)).ToList();
        audit.Check(actualBasis.SequenceEqual(oracle.Basis),"RAW_SELECTED_CHANGED","Raw selected notes removed, reordered or modified");
        bool originRefs=actualRaw.All(n=>song.Notes.Any(source=>ReferenceEquals(source,n)));
        audit.Check(originRefs,"RAW_SOURCE_REPLACED","Arranger output contains a cropped/retimed/fabricated copy rather than a full original source note");
        audit.Check(actualAdded.OrderBy(n=>n.StartMs).ThenBy(n=>n.Track).ThenBy(n=>n.Pitch).SequenceEqual(oracle.Added.OrderBy(n=>n.StartMs).ThenBy(n=>n.Track).ThenBy(n=>n.Pitch)),
            "RAW_ORACLE_MISMATCH","Actual raw additions differ from independent safe-slot priority selection");
        audit.Check(actualAdded.All(n=>!n.Percussion&&selected!=null&&!selected.Contains(n.Track)&&song.Notes.Contains(n)),"ACTUAL_RAW_ORIGIN","Actual added source note is selected/percussion/not an original record");
        audit.Check(actualAdded.All(n=>oracle.Rests.Any(r=>r.LengthMs>=3000-Eps&&n.StartMs>=r.StartMs&&n.StartMs+n.DurationMs<=r.EndMs)),"ACTUAL_RAW_ELIGIBILITY","Actual raw addition is outside an original >=3s raw note-off rest");
        audit.Check(actualAdded.All(n=>oracle.Slots.Any(r=>n.StartMs>=r.StartMs&&n.StartMs+n.DurationMs<=r.EndMs)),"ACTUAL_SLOT_ESCAPE","Actual raw addition does not fit completely in raw-rest/safe-free intersection");
        audit.Check(actualAdded.All(n=>!oracle.Occupied.Any(s=>Overlap(RawSpan(n),s))),"ACTUAL_OCCUPIED_INTRUSION","Actual raw addition invades selected physical/arpeggio/release padding");
        var actualOrdered=actualAdded.OrderBy(n=>n.StartMs).ToList();
        audit.Check(actualOrdered.GroupBy(n=>n.StartMs).All(g=>g.Count()==1)&&actualOrdered.Zip(actualOrdered.Skip(1)).All(x=>x.First.StartMs+x.First.DurationMs<=x.Second.StartMs),"ACTUAL_RAW_POLYPHONY","Actual raw additions overlap or create polyphonic onset");
        audit.Check(originalSong==Program.Serialize(song)&&originalNotes.SequenceEqual(song.Notes)&&onState==Program.Serialize(onOptions),"RAW_INSPECTION_MUTATION","Raw diagnostic mutated source/options");
        audit.SlotProof=new{caseName=name,speed=onOptions.Speed,tracks=onOptions.Tracks,rawBasisNotes=oracle.Basis.Count,rawBasisSha256=Program.HashText(Program.Serialize(oracle.Basis)),
            rawEligibleRests=oracle.Rests,safeOccupiedUnion=oracle.Occupied,safeSlots=oracle.Slots,actualAddedRawNotes=actualAdded,
            fullSourceObjectReferencesPreserved=originRefs,proofBoundary="Public Build main comparisons; supplementary read-only internal raw selection inspection. Eligibility >=3000ms is on original note-off; 8ms physical release padding only narrows usable slots."};
        var orderedAdds=oracle.Added.OrderBy(n=>n.StartMs).ToList();
        audit.Check(orderedAdds.GroupBy(n=>n.StartMs).All(g=>g.Count()==1)&&orderedAdds.Zip(orderedAdds.Skip(1)).All(x=>x.First.StartMs+x.First.DurationMs<=x.Second.StartMs),
            "ADDED_OVERLAP","Added raw line overlaps or has multiple notes at one onset");
        audit.Check(oracle.Added.All(n=>!oracle.Basis.Any(b=>Overlap(RawSpan(n),RawSpan(b)))),"BASIS_INTRUSION","Added raw note intrudes on selected original voice");
        audit.Check(addedPlan.All(n=>!off.Notes.Any(b=>Overlap(SoundSpan(n),SoundSpan(b)))),"PLAN_BASIS_INTRUSION","Added mapped sound intrudes on selected plan sound");
        var orderedPlanAdds=addedPlan.OrderBy(n=>n.StartMs).ToList();
        audit.Check(orderedPlanAdds.GroupBy(n=>n.StartMs).All(g=>g.Count()==1)&&orderedPlanAdds.Zip(orderedPlanAdds.Skip(1)).All(x=>x.First.StartMs+x.First.SoundMs<=x.Second.StartMs+Eps),"PLAN_ADDED_OVERLAP","Added mapped line overlaps");
        audit.Check(on.DurationMs+Eps>=off.DurationMs&&on.DurationMs+Eps>=song.DurationMs/onOptions.Speed,"DURATION_SHORTENED","Smart handoff shortened source timeline/terminal rests");
        audit.Check(on.Report.Output==on.Notes.Count&&off.Report.Output==off.Notes.Count,"OUTPUT_REPORT","Output report mismatch");
        bool nullSame=true;
        if(testNull) {
            var options=offOptions.Copy();options.SmartInterludes=null;string state=Program.Serialize(options);
            var legacy=GameMapping.Build(song,options);
            bool pop=string.Equals(song.Provenance.Provider,"POP909",StringComparison.OrdinalIgnoreCase);
            var target=pop?on:off;
            nullSame=Program.Serialize(legacy.Notes)==Program.Serialize(target.Notes)&&Near(legacy.DurationMs,target.DurationMs)&&legacy.Report==target.Report;
            audit.Check(nullSame,"LEGACY_NULL","Legacy null must auto-enable only for POP909");
            audit.Check(state==Program.Serialize(options)&&originalSong==Program.Serialize(song),"NULL_MUTATION","Legacy build mutated state/source");
        }
        int shortened=addedPlan.Count(n=>n.Sustain&&oracle.Added.Any(r=>r.Track==n.Track&&Near(r.StartMs/onOptions.Speed,n.StartMs)&&n.SoundMs+Eps<r.DurationMs/onOptions.Speed));
        // Existing same-key release safety can reduce plan SoundMs/HoldMs by up to 8ms;
        // it is distinguished from modifying raw source durations, never hidden.
        int changedSelected=before.Count(kv=>after.TryGetValue(kv.Key,out var n)&&(!Near(kv.Value.HoldMs,n.HoldMs)||!Near(kv.Value.SoundMs,n.SoundMs)));
        audit.Check(changedSelected==0,"SELECTED_ENDPOINT_CHANGED","Smart additions changed original selected HoldMs or SoundMs; final safety padding must eliminate old same-key changes",before.Where(kv=>after.TryGetValue(kv.Key,out var n)&&(!Near(kv.Value.HoldMs,n.HoldMs)||!Near(kv.Value.SoundMs,n.SoundMs))).Select(kv=>new{before=kv.Value,after=after[kv.Key]}).ToList());
        var row=new PairRow(name,id,instrument,scenario,onOptions.Speed,onOptions.Transpose,onOptions.Octave,onOptions.Tracks?.ToList(),audit.Assertions,audit.Failures.Count,
            oracle.Basis.Count,oracle.Rests.Count,oracle.Added.Count,oracle.Added.Count(n=>n.Track==2),oracle.Added.Count(n=>n.Track==3),oracle.Segments,addedPlan.Count,
            before.Count,before.Count-missing.Length,off.Report.NativeChords,nativeChanges.Count,changedSelected,shortened,nullSame,Stats(off),Stats(on),Program.HashText(offState),Program.HashText(onState));
        return(row,off,on,oracle,audit);
    }
    internal static object Typical(string id,string instrument,SongDocument song,PlayOptions options,PlaybackPlan off,PlaybackPlan on,Oracle oracle) {
        var tracks=options.Tracks?.ToHashSet();var candidates=song.Notes.Where(n=>tracks!=null&&!tracks.Contains(n.Track)&&!n.Percussion).ToList();
        var rawAfter=oracle.Basis.Concat(oracle.Added).ToList();
        var restDetails=oracle.Rests.Where(r=>r.LengthMs>=5000-Eps).Select(r=>{
            var adds=oracle.Added.Where(n=>n.StartMs>=r.StartMs&&n.StartMs<r.EndMs).ToList();
            var residual=Rests(adds.Select(RawSpan),r.StartMs,r.EndMs).Where(s=>s.LengthMs>=5000-Eps).Select(space=>{
                int full=candidates.Count(n=>n.StartMs>=space.StartMs&&n.StartMs+n.DurationMs<=space.EndMs);
                return new{space,fullUnselectedNonDrumSourceNotes=full,reason=full==0?"No full source note fits; real rest is retained, never fabricated":"Source notes remain but monophonic priority/1.5s piano fallback gates apply; not forced-filled"};
            }).ToList();
            return new{originalRest=r,bridgeAdded=adds.Count(n=>n.Track==2),pianoAdded=adds.Count(n=>n.Track==3),fullCandidates=candidates.Count(n=>n.StartMs>=r.StartMs&&n.StartMs+n.DurationMs<=r.EndMs),residualGe5s=residual};
        }).ToList();
        return new{id,instrument,options,sourceDurationMs=song.DurationMs,sourceFirstSelectedOnsetMs=oracle.Basis.Select(n=>(double?)n.StartMs).Min(),
            sourceFirstAfterHandoffOnsetMs=rawAfter.Select(n=>(double?)n.StartMs).Min(),sourceBasisNoteOffRestsGe5s=Rests(oracle.Basis.Select(RawSpan),0,song.DurationMs).Where(s=>s.LengthMs>=5000-Eps),
            sourceAfterNoteOffRestsGe5s=Rests(rawAfter.Select(RawSpan),0,song.DurationMs).Where(s=>s.LengthMs>=5000-Eps),safeSlots=oracle.Slots,
            off=Stats(off),on=Stats(on),restDetails,boundary="Raw note-off gaps and onset gaps are separate; mapped SoundMs is not measured game decay. No music improvement/fill target is asserted."};
    }
}