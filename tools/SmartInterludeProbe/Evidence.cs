using System.Diagnostics;
using System.Text;
using System.Text.Json;
using QinBan.Core;

internal static partial class Program {
    static async Task<int> Evidence(string repo,string output) {
        using var matrix=JsonDocument.Parse(File.ReadAllText(Path.Combine(repo,".validation","smart-interludes-2026-10-06","matrix-final.json")));
        string expectedHash=matrix.RootElement.GetProperty("summary").GetProperty("coreAssemblySha256").GetString()!;
        if(expectedHash!=LibraryCatalog.HashFile(typeof(GameMapping).Assembly.Location))throw new InvalidOperationException("Evidence Core differs from final matrix Core");
        var entries=Entries(repo,out int count);var recordings=new List<object>();var waves=new List<object>();var failures=new List<Failure>();int assertions=0;
        string stem=Path.Combine(Path.GetDirectoryName(output)!,Path.GetFileNameWithoutExtension(output));
        string stage=Path.Combine(ToolRoot,"wave-staging");Directory.CreateDirectory(stage);
        foreach(string id in new[]{"035","038"}) {
            var entry=entries.Single(e=>e.RelativePath==$"pop909-{id}.json");string score=Path.Combine(repo,"Songs",entry.RelativePath),sourceHash=LibraryCatalog.HashFile(score);var song=SongParser.Read(score);
            var rawMain=song.Notes.Where(n=>entry.Options.Tracks!.Contains(n.Track)&&(!entry.Options.ExcludePercussion||!n.Percussion)).ToList();
            var internalGap=Checks.Rests(rawMain.Select(Checks.RawSpan),0,song.DurationMs).Where(g=>g.StartMs>0&&g.EndMs<song.DurationMs&&g.LengthMs>=5000).OrderByDescending(g=>g.LengthMs).FirstOrDefault();
            double absoluteStart=Math.Max(0,(internalGap?.StartMs??rawMain[0].StartMs)-3500),absoluteEnd=Math.Min(song.DurationMs,absoluteStart+29550);
            foreach(var instrument in InstrumentCatalog.All.Where(i=>i.CanAutoPlay)) {
                var audit=new Audit($"recording/{id}/{instrument.Id}");var pair=Checks.Pair(id,"evidence",song,entry.Options,instrument.Id);assertions+=pair.Audit.Assertions;failures.AddRange(pair.Audit.Failures);
                var options=entry.Options.Copy();options.InstrumentId=instrument.Id;options.SmartInterludes=true;options.Loop=false;
                string state=Serialize(options);var offKeys=pair.Off.Notes.Select(n=>(n.Key,n.StartMs)).ToHashSet();
                double start=pair.On.Notes.Where(n=>!offKeys.Contains((n.Key,n.StartMs))).Select(n=>n.StartMs).DefaultIfEmpty(pair.On.Notes[0].StartMs).Min();
                double end=Math.Min(pair.On.DurationMs,start+2000);const double accelerate=4;
                var originalFragment=pair.On.Notes.Where(n=>n.StartMs>=start&&n.StartMs<end).Select(n=>n with {StartMs=n.StartMs-start,HoldMs=Math.Min(n.HoldMs,end-n.StartMs),SoundMs=Math.Min(n.SoundMs,end-n.StartMs)}).ToList();
                var scheduled=originalFragment.Select(n=>n with {StartMs=n.StartMs/accelerate,HoldMs=n.HoldMs/accelerate,SoundMs=n.SoundMs/accelerate}).ToList();
                var fragment=new PlaybackPlan(scheduled,(end-start)/accelerate,pair.On.Report,["Accelerated managed scheduler smoke, no audio or OS input"]);
                var sink=new RecordingSink(instrument.Keys.Select(k=>k.Key).ToHashSet());int guardCalls=0;
                var engine=new PlaybackEngine(sink,()=>{guardCalls++;return new InputGuard(true);});var watch=Stopwatch.StartNew();PlaybackResult? result=null;string? error=null;
                try {result=await engine.PlayAsync(fragment,options).WaitAsync(TimeSpan.FromSeconds(5));}
                catch(Exception ex){error=ex.ToString();engine.Stop("sidecar timeout/error");}
                watch.Stop();
                var expectedEvents=scheduled.SelectMany(n=>new[]{(At:n.StartMs,Down:true,n.Key),(At:Math.Min(fragment.DurationMs,n.StartMs+n.HoldMs),Down:false,n.Key)})
                    .GroupBy(e=>e.At).OrderBy(g=>g.Key).SelectMany(g=>new[]{new{kind="release",keys=string.Concat(g.Where(e=>!e.Down).Select(e=>e.Key).Distinct())},new{kind="press",keys=string.Concat(g.Where(e=>e.Down).Select(e=>e.Key).Distinct())}})
                    .Where(x=>x.keys.Length>0).Select(x=>x.kind+":"+x.keys).ToArray();
                var observed=sink.Events.Where(e=>e.Kind!="release-all").Select(e=>e.Kind+":"+e.Keys).ToArray();
                audit.Check(result?.Completed==true&&error==null,"SCHEDULER_INCOMPLETE","Actual PlaybackEngine did not complete",new{result,error});
                audit.Check(result?.NotesPressed==scheduled.Count&&sink.DownCount==scheduled.Count,"ATTACK_COUNT","Recorded attacks differ from exact fragment",new{expected=scheduled.Count,sink.DownCount,result?.NotesPressed});
                audit.Check(expectedEvents.SequenceEqual(observed),"EVENT_ORDER","Actual press/release batches or order differ from expected scheduler events",new{expectedEvents,observed});
                audit.Check(sink.HeldCount==0&&!engine.IsRunning&&sink.DuplicateDowns==0&&sink.OrphanReleases==0&&sink.ReleaseAllCount>=2,"HELD_LEAK","Held key, duplicate press, orphan release or missing cleanup",new{sink.HeldCount,sink.DuplicateDowns,sink.OrphanReleases,sink.ReleaseAllCount});
                audit.Check(end-start<=2000&&fragment.DurationMs<=2000&&watch.Elapsed.TotalMilliseconds<=2000,"RECORDING_TOO_LONG","Fragment or actual wall duration exceeds two seconds");
                audit.Check(state==Serialize(options)&&guardCalls>0,"STATE_OR_GUARD","Options changed or actual input guard not exercised");
                string recordPath=ValidateOutput(repo,$"{stem}-record-{id}-{instrument.Id}.json");
                var record=new{id,instrument=instrument.Id,status=audit.Failures.Count==0?"PASS_RECORDING_SINK":"FAIL",sourceAbsoluteStartMs=start,sourceAbsoluteEndMs=end,
                    originalPlanFragmentLengthMs=end-start,schedulerDurationMs=fragment.DurationMs,timeCompressionFactor=accelerate,elapsedWallMs=watch.Elapsed.TotalMilliseconds,
                    originalFragmentNotes=originalFragment,scheduledNotes=scheduled,expectedEvents,recordedEvents=sink.Events,result,guardCalls,
                    sink.DownCount,heldKeysAfter=sink.HeldCount,sink.ReleaseAllCount,sink.DuplicateDowns,sink.OrphanReleases,assertions=audit.Assertions,failures=audit.Failures,
                    ignoredCarryInNotes=pair.On.Notes.Count(n=>n.StartMs<start&&n.StartMs+n.HoldMs>start),
                    boundary="Actual PlaybackEngine injected RecordingSink only; <=2s original fragment, 4x scheduler-only compression. No native sink, no audio played, not original-speed music evidence or full-song playback."};
                WriteNew(recordPath,record);recordings.Add(new{id,instrument=instrument.Id,status=audit.Failures.Count==0?"PASS":"FAIL",file=recordPath,notes=scheduled.Count,heldAfter=sink.HeldCount,wallMs=watch.Elapsed.TotalMilliseconds,sourceStartMs=start,sourceEndMs=end});assertions+=audit.Assertions;failures.AddRange(audit.Failures);
                if(instrument.Id is "windsong" or "harmonic")foreach(var variant in new[]{(Name:"off",Plan:pair.Off),(Name:"on",Plan:pair.On)}) {
                    var wa=new Audit($"wave/{id}/{instrument.Id}/{variant.Name}");
                    var notes=variant.Plan.Notes.Where(n=>n.StartMs<absoluteEnd&&n.StartMs+n.SoundMs>absoluteStart)
                        .Select(n=>n with {StartMs=Math.Max(0,n.StartMs-absoluteStart),HoldMs=Math.Max(.1,Math.Min(n.HoldMs,absoluteEnd-Math.Max(n.StartMs,absoluteStart))),
                            SoundMs=Math.Min(n.StartMs+n.SoundMs,absoluteEnd)-Math.Max(n.StartMs,absoluteStart)}).ToList();
                    string name=$"{Path.GetFileName(stem)}-{id}-{instrument.Id}-smart-{variant.Name}-max30s.wav",staged=Path.Combine(stage,name),target=ValidateOutput(repo,Path.Combine(Path.GetDirectoryName(output)!,name));
                    double returned=PreviewAudio.WriteWave(new(notes,absoluteEnd-absoluteStart,variant.Plan.Report,["Same absolute window; software synthesized comparison only"]),staged);
                    byte[] bytes=File.ReadAllBytes(staged);int sampleCount=(bytes.Length-44)/2;int peak=0,nonZero=0,clipped=0;double energy=0;
                    for(int i=44;i<bytes.Length;i+=2){int v=BitConverter.ToInt16(bytes,i);peak=Math.Max(peak,Math.Abs(v));if(v!=0)nonZero++;if(Math.Abs(v)>=32767)clipped++;energy+=(double)v*v;}
                    double actualMs=sampleCount*1000.0/PreviewAudio.SampleRate;
                    wa.Check(Encoding.ASCII.GetString(bytes,0,4)=="RIFF"&&Encoding.ASCII.GetString(bytes,8,8)=="WAVEfmt "&&Encoding.ASCII.GetString(bytes,36,4)=="data"&&
                        BitConverter.ToInt16(bytes,20)==1&&BitConverter.ToInt16(bytes,22)==1&&BitConverter.ToInt32(bytes,24)==PreviewAudio.SampleRate&&
                        BitConverter.ToInt16(bytes,34)==16&&BitConverter.ToInt32(bytes,40)==bytes.Length-44&&BitConverter.ToInt32(bytes,4)==bytes.Length-8,"PCM_HEADER","WAV is not valid mono16 PCM");
                    wa.Check(actualMs<=30000+1000.0/PreviewAudio.SampleRate&&Math.Abs(returned-actualMs)<=1000.0/PreviewAudio.SampleRate,"WAVE_DURATION","WAV exceeds 30 seconds or duration disagrees with PCM");
                    wa.Check(nonZero>0&&peak>0&&clipped==0,"PCM_SILENCE_OR_CLIP","PCM is entirely silent or has saturated samples",new{nonZero,peak,clipped});
                    File.Copy(staged,target,false);
                    waves.Add(new{id,instrument=instrument.Id,smart=variant.Name,status=wa.Failures.Count==0?"PASS_PCM":"FAIL",file=target,sha256=LibraryCatalog.HashFile(target),
                        absoluteWindowStartMs=absoluteStart,absoluteWindowEndMs=absoluteEnd,sourceWindowLengthMs=absoluteEnd-absoluteStart,pcmDurationMs=actualMs,sampleCount,
                        sampleRate=PreviewAudio.SampleRate,channels=1,bits=16,peak,nonZeroSamples=nonZero,saturatedSamples=clipped,rms=Math.Sqrt(energy/sampleCount),plannedFragmentNotes=notes.Count,
                        carryInClippedAndReattacked=variant.Plan.Notes.Count(n=>n.StartMs<absoluteStart&&n.StartMs+n.SoundMs>absoluteStart),carryOutClipped=variant.Plan.Notes.Count(n=>n.StartMs<absoluteEnd&&n.StartMs+n.SoundMs>absoluteEnd),
                        softwareSynthesized=true,played=false,realGameMeasured=false,boundary="Identical absolute window for both smart flags and both instruments for each song. PreviewAudio synthetic envelope, per-clip gain, boundary notes clipped/re-attacked for the fragment only. No game samples, no listening/music certification."});
                    assertions+=wa.Assertions;failures.AddRange(wa.Failures);
                }
            }
            if(sourceHash!=LibraryCatalog.HashFile(score))failures.Add(new("evidence/"+id,"SOURCE_CHANGED","Source file hash changed"));
        }
        var final=new Audit("evidence/final");final.Check(recordings.Count==18,"RECORD_COUNT","Expected two songs by nine instrument recordings");final.Check(waves.Count==8,"WAVE_COUNT","Expected two songs by two instruments by two smart flags");
        final.Check(waves.Select(w=>JsonSerializer.SerializeToElement(w)).GroupBy(w=>w.GetProperty("id").GetString()).All(g=>g.Select(w=>(w.GetProperty("absoluteWindowStartMs").GetDouble(),w.GetProperty("absoluteWindowEndMs").GetDouble())).Distinct().Count()==1),"WINDOW_MISMATCH","Absolute window differs between flags/instruments");
        assertions+=final.Assertions;failures.AddRange(final.Failures);
        string failurePath=ValidateOutput(repo,stem+"-failures.json");WriteNew(failurePath,failures);
        var summary=new{status=failures.Count==0?"PASS_SYNTHETIC_PCM_AND_RECORDING_SINK":"FAIL",catalogEntries=count,recordingCases=recordings.Count,recordingFailures=recordings.Count(r=>JsonSerializer.SerializeToElement(r).GetProperty("status").GetString()=="FAIL"),
            waves=waves.Count,waveFailures=waves.Count(w=>JsonSerializer.SerializeToElement(w).GetProperty("status").GetString()=="FAIL"),assertions,failureAssertions=failures.Count,coreAssemblySha256=expectedHash,
            audioPlayed=false,nativeKeySendAttempts=0,realGameTested=false,fullSongPlaybackTested=false,boundary="Generated, PCM-validated software synthesis only. Actual managed PlaybackEngine RecordingSink smoke, 4x accelerated, no music timing/acoustic/game certification."};
        WriteNew(output,new{summary,recordings,waves});Console.WriteLine(Serialize(summary));return failures.Count==0?0:1;
    }
}
internal sealed record RecordedEvent(string Kind,string Keys,double WallMs,int HeldAfter);
internal sealed class RecordingSink(HashSet<char> allowed):IKeySink {
    readonly HashSet<char> held=[];readonly Stopwatch clock=Stopwatch.StartNew();
    public List<RecordedEvent> Events {get;}=[];public int DownCount{get;private set;}public int HeldCount=>held.Count;
    public int DuplicateDowns{get;private set;}public int OrphanReleases{get;private set;}public int ReleaseAllCount{get;private set;}
    public void Press(IReadOnlyList<char> keys){foreach(char k in keys){if(!allowed.Contains(k))throw new InvalidOperationException("Illegal recorder key");if(!held.Add(k)){DuplicateDowns++;throw new InvalidOperationException("Held repeated key");}}DownCount+=keys.Count;Events.Add(new("press",string.Concat(keys),clock.Elapsed.TotalMilliseconds,held.Count));}
    public void Release(IReadOnlyList<char> keys){foreach(char k in keys)if(!held.Remove(k))OrphanReleases++;Events.Add(new("release",string.Concat(keys),clock.Elapsed.TotalMilliseconds,held.Count));}
    public void ReleaseAll(){held.Clear();ReleaseAllCount++;Events.Add(new("release-all","",clock.Elapsed.TotalMilliseconds,held.Count));}
}