using System.Diagnostics;
using System.Text.Json;
using QinBan.Core;

if (args.Length != 2) { Console.Error.WriteLine("<passed-build-output> <NEW-report.json>"); return 2; }
string stage = Path.GetFullPath(args[0]), reportPath = Path.GetFullPath(args[1]);
if (File.Exists(reportPath)) throw new IOException("Refusing to overwrite report");
using var build = JsonDocument.Parse(File.ReadAllText(Path.Combine(stage,"build-report.json")));
if (!build.RootElement.GetProperty("status").GetString()!.StartsWith("PASS_SOURCE_COMPARED")) throw new InvalidOperationException("Only verified build accepted");
var ids = build.RootElement.GetProperty("sampleIds").EnumerateArray().Select(v=>v.GetString()!).ToList();
var results = new List<object>(); var gate = new object();
var jobs = ids.Select(async id => {
    foreach (var instrument in InstrumentCatalog.All.Where(p=>p.CanAutoPlay)) {
        var watch = Stopwatch.StartNew();
        try {
            string scorePath=Path.Combine(stage,"Songs","pop909-"+id+".json"); string hash=LibraryCatalog.HashFile(scorePath);
            using var doc=JsonDocument.Parse(File.ReadAllText(Path.Combine(stage,"sample-plans",$"pop909-{id}.{instrument.Id}.plan.json")));
            var options=doc.RootElement.GetProperty("options").Deserialize<PlayOptions>(JsonDefaults.Options)!;
            var full=doc.RootElement.GetProperty("plan").Deserialize<PlaybackPlan>(JsonDefaults.Options)!;
            double sourceStart=full.Notes.Min(n=>n.StartMs), sourceEnd=Math.Min(full.DurationMs,sourceStart+2000), length=sourceEnd-sourceStart;
            var notes=full.Notes.Where(n=>n.StartMs>=sourceStart && n.StartMs<sourceEnd).Select(n=>n with {StartMs=n.StartMs-sourceStart,HoldMs=Math.Min(n.HoldMs,sourceEnd-n.StartMs),SoundMs=Math.Min(n.SoundMs,sourceEnd-n.StartMs)}).ToList();
            var fragment=new PlaybackPlan(notes,length,full.Report,["Recorder-only two-second smoke segment; not full-song/game test"]);
            var recorder=new Recorder(instrument.Keys.Select(k=>k.Key).ToHashSet());
            var engine=new PlaybackEngine(recorder,()=>new InputGuard(true));
            var outcome=await engine.PlayAsync(fragment,options).WaitAsync(TimeSpan.FromSeconds(15));
            if (!outcome.Completed || outcome.NotesPressed!=notes.Count || recorder.DownCount!=notes.Count || recorder.HeldCount!=0 || engine.IsRunning)
                throw new InvalidOperationException("Incomplete schedule, leaked held key, or mismatched attacks");
            var expected=notes.GroupBy(n=>n.StartMs).OrderBy(g=>g.Key).Select(g=>string.Concat(g.Select(n=>n.Key).Distinct())).ToArray();
            if (!expected.SequenceEqual(recorder.Batches)) throw new InvalidOperationException("Scheduled attack batches/order differ from full plan segment");
            if (LibraryCatalog.HashFile(scorePath)!=hash) throw new InvalidOperationException("Source changed");
            lock(gate) results.Add(new {id,instrument=instrument.Id,status="PASS",segmentStartMs=sourceStart,segmentLengthMs=length,notes=notes.Count,notesPressed=outcome.NotesPressed,heldKeysAfter=recorder.HeldCount,elapsedMs=watch.Elapsed.TotalMilliseconds,originalRhythmNotTimeCompressed=true});
        } catch(Exception ex) {lock(gate) results.Add(new {id,instrument=instrument.Id,status="FAIL",error=ex.ToString()});}
    }
}).ToArray();
await Task.WhenAll(jobs);
int failures=results.Count(r=>JsonSerializer.SerializeToElement(r).GetProperty("status").GetString()=="FAIL");
var report=new {status=failures==0?"PASS_RECORDER_ONLY":"FAIL",cases=results.Count,failures,nativeKeySendAttempts=0,audioPlayed=false,realGameTested=false,fullSongPlaybackTested=false,scope="Five seeded samples x nine instruments; actual managed scheduler with injected recorder, two-second original-timing segments",results};
Directory.CreateDirectory(Path.GetDirectoryName(reportPath)!);using(var f=new FileStream(reportPath,FileMode.CreateNew)) JsonSerializer.Serialize(f,report,JsonDefaults.Options);
Console.WriteLine($"RESULT recorder: {results.Count-failures}/{results.Count}; native=0; game=false");return failures==0 && results.Count==45?0:1;

sealed class Recorder(HashSet<char> allowed):IKeySink {
    readonly HashSet<char> held=[];public List<string>Batches{get;}=[];public int DownCount{get;private set;}public int HeldCount=>held.Count;
    public void Press(IReadOnlyList<char> keys){foreach(char k in keys){if(!allowed.Contains(k)||!held.Add(k))throw new InvalidOperationException("Illegal key or unreleased repeated key");}DownCount+=keys.Count;Batches.Add(string.Concat(keys));}
    public void Release(IReadOnlyList<char> keys){foreach(char k in keys)held.Remove(k);}
    public void ReleaseAll()=>held.Clear();
}
