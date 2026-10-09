using QinBan.Core;
internal static partial class Program {
    static int Fixtures(string repo,string output) {
        var rows=new List<PairRow>();var failures=new List<Failure>();var proofs=new List<object>();int assertions=0,nativeChords=0;
        SongDocument Song(double length,List<NoteEvent> notes,string provider="POP909")=>new(){Title="Sidecar-only deterministic fixture",LengthMs=length,Notes=notes,Provenance=new(){Provider=provider,Synthetic=true}};
        PlayOptions Opt(double speed=1,List<int>? tracks=null)=>new(){Tracks=tracks??[1],Speed=speed,SmartInterludes=true};
        void Run(string name,SongDocument song,PlayOptions options,string instrument,int expectedAdded,Action<Oracle,Audit>? verify=null,int expectedNative=0) {
            try {var r=Checks.Pair(name,"fixture",song,options,instrument);r.Audit.Check(r.On.Report.InterludeNotes==expectedAdded,"FIXTURE_ADDITIONS","Fixture raw-addition count differs",new{expectedAdded,actual=r.On.Report.InterludeNotes});
                r.Audit.Check(r.Off.Report.NativeChords==expectedNative&&r.On.Report.NativeChords==expectedNative,"FIXTURE_NATIVE","Existing native chord coverage differs",new{expectedNative,off=r.Off.Report.NativeChords,on=r.On.Report.NativeChords});
                verify?.Invoke(r.Oracle,r.Audit);rows.Add(r.Row with {Assertions=r.Audit.Assertions,Failures=r.Audit.Failures.Count});proofs.Add(r.Audit.SlotProof!);assertions+=r.Audit.Assertions;failures.AddRange(r.Audit.Failures);nativeChords+=r.Off.Report.NativeChords;
            }catch(Exception ex){failures.Add(new(name,"FIXTURE_EXCEPTION",ex.Message,ex.ToString()));}
        }
        foreach(double speed in new[]{.5,1.0,2.0}) foreach(double gap in new[]{2999.0,3000.0}) {
            var song=Song(gap+2000,[new(60,0,1000,1),new(62,gap+1000,1000,1),new(67,1500,500,2)]);
            Run($"threshold-{gap}-speed-{speed}",song,Opt(speed),"harmonic",gap==3000?1:0,(o,a)=>a.Check(gap!=3000||o.Slots.Any(s=>s.LengthMs<3000),"RAW_THRESHOLD_REAPPLIED","Exact >=3s musical rest must remain eligible after safe-window narrowing"));
        }
        foreach(double speed in new[]{.5,1.0,2.0}) {
            double safe=1000+8*speed;
            var song=Song(5000,[new(60,0,1000,1),new(62,4000,1000,1),new(60,1000,100,2),new(60,safe,100,2)]);
            Run("padded-edge-"+speed,song,Opt(speed),"harmonic",1,(o,a)=>a.Check(o.Added.Single().StartMs==safe,"SAFE_EDGE","Raw note-off-edge candidate must be rejected whole and safe-edge original accepted"));
        }
        foreach(double residual in new[]{1499.0,1500.0}) {
            var song=Song(6000,[new(60,0,1000,1),new(62,5000,1000,1),new(72,1100,3900-residual,2),new(79,3700,500,3)]);
            Run("piano-residual-"+residual,song,Opt(),"windsong",residual==1500?2:1,(o,a)=>a.Check(o.Added.Any(n=>n.Track==3)==(residual==1500),"PIANO_FALLBACK","1.5s residual threshold differs"));
        }
        Run("reject-partial-and-percussion",Song(6000,[new(60,0,1000,1),new(62,5000,1000,1),new(67,900,2000,2),new(70,4000,2000,2),new(72,2200,500,3,100,true)]),Opt(),"windsong",0);
        Run("held-basis-not-onset-gap",Song(9000,[new(60,0,8000,1),new(62,8500,500,1),new(72,3000,500,2)]),Opt(),"harmonic",0);
        Run("nested-basis-union",Song(10500,[new(60,0,9000,1),new(64,2000,250,1),new(62,10000,500,1),new(72,4000,500,2)]),Opt(),"harmonic",0);
        Run("leading-trailing",Song(10000,[new(60,4000,1000,1),new(72,0,500,2),new(74,6000,500,2)]),Opt(),"windsong",2);
        Run("user-tracks12-piano",Song(8000,[new(60,0,1000,1),new(62,7000,1000,1),new(72,2000,1000,2),new(67,1500,200,3),new(79,3500,500,3)]),Opt(tracks:[1,2]),"windsong",1,(o,a)=>a.Check(o.Added.Single().Track==3,"TRACKS12_PIANO","Manual [1,2] must retain both basis voices and use only source piano for rest"));
        Run("same-onset-one-fitting-high-voice",Song(6000,[new(60,0,1000,1),new(62,5000,1000,1),new(85,1500,4000,2),new(74,1500,500,2),new(60,1500,500,2),new(90,1500,100,3)]),Opt(),"windsong",1,(o,a)=>a.Check(o.Added.Single().Pitch==74&&o.Added.Single().Track==2,"VOICE_PRIORITY","Highest full-fitting primary source voice must win before piano"));
        Run("real-unfillable-rest",Song(15000,[new(60,0,500,1),new(62,10000,500,1),new(72,50,200,2),new(67,10100,200,3)]),Opt(),"windsong",0,(o,a)=>a.Check(Checks.Rests(o.Basis.Concat(o.Added).Select(Checks.RawSpan),0,15000).Any(s=>s.LengthMs>=5000),"FORCED_FILL","Real all-source rest must not be synthesized"));
        Run("explicit-true-local-provider",Song(6000,[new(60,0,1000,1),new(62,5000,1000,1),new(72,2000,500,2)],"local"),Opt(),"windsong",1);
        Run("all-tracks-selected",Song(6000,[new(60,0,1000,1),new(62,5000,1000,1),new(72,2000,500,2)]),Opt(tracks:[1,2]),"windsong",0);
        foreach(string instrument in new[]{"ukulele","euphonia"})foreach(var key in InstrumentCatalog.Get(instrument).Keys.Where(k=>k.IsChord)) {
            var notes=key.Pitches.Select(p=>new NoteEvent(p,1000,500,1)).ToList();notes.AddRange([new(60,10000,500,1),new(69,1000,300,2),new(74,4000,500,2),new(79,7000,500,3)]);
            Run("native-"+instrument+"-"+key.Key,Song(10500,notes),Opt(),instrument,2,expectedNative:1);
        }
        foreach(var mode in new[]{ChordMode.Ascending,ChordMode.Descending})foreach(double speed in new[]{.5,2.0}) {
            var options=Opt(speed);options.Chords=mode;options.StrumMs=100;
            Run($"arpeggio-{mode}-{speed}",Song(8500,[new(60,1000,10,1),new(64,1000,10,1),new(67,1000,10,1),new(62,8000,500,1),new(72,1020,200,2),new(74,2000,500,2)]),options,"euphonia",1);
        }
        var direct=new Audit("direct-empty-all-cancelled");var sample=Song(6000,[new(60,0,500,1),new(62,5500,500,1),new(72,2000,500,2)]);string raw=Serialize(sample);
        foreach(var tracks in new List<int>?[]{null,[]}){var options=new PlayOptions{Tracks=tracks,SmartInterludes=true};var p=GameMapping.Build(sample,options);direct.Check(p.Report.InterludeNotes==0&&p.Report.InterludeSegments==0,"EMPTY_OR_ALL_TRACKS","No selection/all tracks must not create extra source notes");}
        using(var cancel=new CancellationTokenSource()){cancel.Cancel();bool threw=false;try{GameMapping.Build(sample,Opt(),cancel.Token);}catch(OperationCanceledException){threw=true;}direct.Check(threw&&raw==Serialize(sample),"CANCEL_MUTATION","Pre-cancelled Build must not mutate source");}
        var metric=Checks.Rests([new(0,7000),new(1000,2000),new(6000,8000),new(13000,14000)],0,15000);direct.Check(metric.SequenceEqual(new Span[]{new(8000,13000),new(14000,15000)}),"UNION_METRIC","Independent gap union failed nested/overlap fixture");
        assertions+=direct.Assertions;failures.AddRange(direct.Failures);
        string stem=Path.Combine(Path.GetDirectoryName(output)!,Path.GetFileNameWithoutExtension(output));WriteNew(ValidateOutput(repo,stem+"-failures.json"),failures);
        var summary=new{status=failures.Count==0?"PASS_INDEPENDENT_RULE_FIXTURES":"FAIL",pairedCases=rows.Count,directCases=4,nativeGuitarChordCases=14,nativeGuitarChordsPreserved=nativeChords,assertions,failureAssertions=failures.Count,
            coreAssemblySha256=LibraryCatalog.HashFile(typeof(GameMapping).Assembly.Location),boundary="In-memory deterministic fixtures only; thresholds and full-source/safe-slot properties independently asserted. No song quality/fill targets, no native output."};
        WriteNew(output,new{summary,rows,proofs});Console.WriteLine(Serialize(summary));return failures.Count==0?0:1;
    }
}