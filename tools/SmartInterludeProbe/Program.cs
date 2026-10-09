using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using QinBan.Core;

internal static partial class Program {
    internal static string ToolRoot=>Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../.."));
    internal static string Serialize<T>(T item)=>JsonSerializer.Serialize(item,JsonDefaults.Options);
    internal static string HashText(string s)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();
    internal static void WriteNew<T>(string p,T item) {using var f=new FileStream(p,FileMode.CreateNew,FileAccess.Write,FileShare.None);JsonSerializer.Serialize(f,item,JsonDefaults.Options);}
    internal static void WriteTextNew(string p,string text) {using var f=new FileStream(p,FileMode.CreateNew,FileAccess.Write,FileShare.None);using var w=new StreamWriter(f,new UTF8Encoding(false));w.Write(text);}
    internal static string ValidateOutput(string repo,string path) {
        path=Path.GetFullPath(path);string allowed=Path.Combine(repo,".validation","smart-interludes-2026-10-06");
        if(Path.GetDirectoryName(path)!=allowed || !Path.GetFileName(path).StartsWith("matrix-",StringComparison.Ordinal) || File.Exists(path))
            throw new InvalidOperationException("Only NEW direct matrix-* files are allowed: "+path);
        if(!Directory.Exists(allowed))throw new DirectoryNotFoundException(allowed);return path;
    }
    internal static List<LibraryEntry> Entries(string repo,out int count) {
        var entries=new List<LibraryEntry>();
        using var c=new SqliteConnection(new SqliteConnectionStringBuilder{DataSource=Path.Combine(repo,"Songs","catalog.db"),Mode=SqliteOpenMode.ReadOnly,Pooling=false}.ToString());c.Open();
        using var cmd=c.CreateCommand();cmd.CommandText="SELECT COUNT(*) FROM entries";count=Convert.ToInt32(cmd.ExecuteScalar());
        cmd.CommandText="SELECT metadata_json FROM entries WHERE relative_path LIKE 'pop909-%' ORDER BY relative_path";using var r=cmd.ExecuteReader();
        while(r.Read())entries.Add(JsonSerializer.Deserialize<LibraryEntry>(r.GetString(0),JsonDefaults.Options)!);
        if(entries.Count!=100||entries.Select(e=>e.RelativePath).Distinct().Count()!=100)throw new InvalidOperationException("Expected 100 distinct POP909 entries");return entries;
    }
    static async Task<int> Main(string[] args) {
        try {
            if(args.Length!=3)throw new ArgumentException("--matrix|--evidence|--fixtures <repo> <NEW matrix-*.json>");
            string repo=Path.GetFullPath(args[1]),output=ValidateOutput(repo,args[2]);
            return args[0] switch {"--matrix"=>Matrix(repo,output),"--evidence"=>await Evidence(repo,output),"--fixtures"=>Fixtures(repo,output),_=>throw new ArgumentException("Unknown command")};
        } catch(Exception ex) {Console.Error.WriteLine(ex);return 2;}
    }
    static int Matrix(string repo,string output) {
        var watch=Stopwatch.StartNew();string catalog=Path.Combine(repo,"Songs","catalog.db"),beforeCatalog=LibraryCatalog.HashFile(catalog);
        var entries=Entries(repo,out int catalogCount);var instruments=InstrumentCatalog.All.Where(i=>i.CanAutoPlay).ToArray();var drums=InstrumentCatalog.All.Where(i=>!i.CanAutoPlay).ToArray();
        if(instruments.Length!=9||drums.Length!=3)throw new InvalidOperationException("Expected nine enabled instruments and three blocked drums");
        var rows=new List<PairRow>();var extra=new List<PairRow>();var blocked=new List<object>();var sourceEvidence=new List<object>();var failures=new List<Failure>();var typical=new List<object>();var slotEvidence=new List<object>();
        int assertions=0,blockedBuilds=0,buildExceptions=0;
        var allFiles=Directory.GetFiles(Path.Combine(repo,"Songs"),"*",SearchOption.TopDirectoryOnly).Order().Select(p=>new{path=p,sha256=LibraryCatalog.HashFile(p)}).ToArray();
        foreach(var entry in entries) {
            string id=Path.GetFileNameWithoutExtension(entry.RelativePath).Replace("pop909-","");string path=Path.Combine(repo,"Songs",entry.RelativePath);
            if(entry.RelativePath!=$"pop909-{id}.json"||id.Length!=3||!id.All(char.IsAsciiDigit))throw new InvalidOperationException("Unexpected resource path");
            string hash=LibraryCatalog.HashFile(path);var song=SongParser.Read(path);string original=Serialize(song),notesHash=HashText(Serialize(song.Notes)),options=Serialize(entry.Options);
            var sa=new Audit("source/"+id);sa.Check(hash.Equals(entry.ResourceHash,StringComparison.OrdinalIgnoreCase),"CATALOG_RESOURCE_HASH","Source does not match read-only catalog ResourceHash");
            sa.Check(entry.Options.Tracks!=null&&entry.Options.Tracks.SequenceEqual(new[]{1}),"CATALOG_BASE_TRACKS","Catalog selection is not original [1]");
            sa.Check(entry.Options.Chords==ChordMode.Simultaneous,"CATALOG_CHORD_MODE","Catalog chord mode is not simultaneous");
            sa.Check(entry.Options.SmartInterludes==null,"CATALOG_LEGACY_STATE","Catalog legacy state is not null; explicit false is used for old-plan baseline");
            void Run(string scenario,PlayOptions opts,string instrument,bool sample) {
                try {
                    var result=Checks.Pair(id,scenario,song,opts,instrument);
                    (sample?extra:rows).Add(result.Row);assertions+=result.Audit.Assertions;failures.AddRange(result.Audit.Failures);slotEvidence.Add(result.Audit.SlotProof!);
                    if(!sample&&id is "035" or "038")typical.Add(Checks.Typical(id,instrument,song,opts,result.Off,result.On,result.Oracle));
                } catch(Exception ex){buildExceptions++;failures.Add(new($"{scenario}/{id}/{instrument}","BUILD_EXCEPTION",ex.Message,ex.ToString()));}
            }
            foreach(var instrument in instruments) Run("catalog-tracks1",entry.Options,instrument.Id,false);
            foreach(var drum in drums) {
                var a=new Audit($"drum/{id}/{drum.Id}");var plans=new List<PlaybackPlan>();
                foreach(bool? enabled in new bool?[]{false,true,null}) {
                    var opt=entry.Options.Copy();opt.InstrumentId=drum.Id;opt.SmartInterludes=enabled;string state=Serialize(opt);
                    try {var p=GameMapping.Build(song,opt);blockedBuilds++;plans.Add(p);
                        a.Check(p.Notes.Count==0&&p.DurationMs==0&&p.Report.InterludeNotes==0&&p.Report.InterludeSegments==0,"DRUM_UNSAFE","Disabled drum generated a plan or arrangement");
                        a.Check(state==Serialize(opt)&&original==Serialize(song),"DRUM_MUTATION","Blocked drum build mutated source/options");
                    }catch(Exception ex){a.Check(false,"DRUM_EXCEPTION",ex.Message);}
                }
                blocked.Add(new{id,instrument=drum.Id,builds=plans.Count,assertions=a.Assertions,failures=a.Failures.Count,status=a.Failures.Count==0?"PASS_BLOCKED":"FAIL"});assertions+=a.Assertions;failures.AddRange(a.Failures);
            }
            if(id is "035" or "038") {
                foreach(double speed in new[]{2.0,0.5})foreach(var instrument in instruments){var opt=entry.Options.Copy();opt.Speed=speed;Run("speed-"+speed.ToString(System.Globalization.CultureInfo.InvariantCulture),opt,instrument.Id,true);}
                foreach(var instrument in instruments){var opt=entry.Options.Copy();opt.Tracks=[1,2];Run("user-tracks12",opt,instrument.Id,true);}
                foreach(string instrument in new[]{"voice","ukulele","euphonia"})foreach(int transpose in new[]{-2,2}){var opt=entry.Options.Copy();opt.Transpose=transpose;opt.Octave=transpose<0?-1:1;Run("cross-voice-guitar-transpose-"+transpose,opt,instrument,true);}
            }
            sa.Check(hash==LibraryCatalog.HashFile(path)&&original==Serialize(song)&&notesHash==HashText(Serialize(song.Notes)),"SOURCE_AFTER","Source file/document/raw-note hash changed");
            sa.Check(options==Serialize(entry.Options),"CATALOG_OPTIONS_MUTATED","Read-only catalog options changed in memory");assertions+=sa.Assertions;failures.AddRange(sa.Failures);
            sourceEvidence.Add(new{id,path,fileHashBefore=hash,fileHashAfter=LibraryCatalog.HashFile(path),rawNotes=song.Notes.Count,rawNotesHashBefore=notesHash,rawNotesHashAfter=HashText(Serialize(song.Notes)),selectedOptionsHash=HashText(options)});
            if(sourceEvidence.Count%10==0)Console.WriteLine($"MATRIX {sourceEvidence.Count}/100: pairs={rows.Count} blocked={blocked.Count} failureAssertions={failures.Count}");
        }
        var integrity=new Audit("matrix/final-integrity");
        integrity.Check(allFiles.All(f=>File.Exists(f.path)&&f.sha256==LibraryCatalog.HashFile(f.path)),"SONGS_HASH_CHANGED","One or more Songs/catalog files changed during matrix");
        integrity.Check(allFiles.Length==Directory.GetFiles(Path.Combine(repo,"Songs"),"*",SearchOption.TopDirectoryOnly).Length,"SONGS_FILE_COUNT_CHANGED","Songs file count changed during matrix");
        integrity.Check(beforeCatalog==LibraryCatalog.HashFile(catalog),"CATALOG_CHANGED","Catalog SHA256 changed");
        integrity.Check(rows.Count==900&&blocked.Count==300&&blockedBuilds==900,"MATRIX_INCOMPLETE","Expected 900 off/on comparisons and 300 blocked drum combinations (three flags each)");
        assertions+=integrity.Assertions;failures.AddRange(integrity.Failures);
        string stem=Path.Combine(Path.GetDirectoryName(output)!,Path.GetFileNameWithoutExtension(output));
        string csv=ValidateOutput(repo,stem+".csv"),failureOutput=ValidateOutput(repo,stem+"-failures.json"),typicalOutput=ValidateOutput(repo,stem+"-typical.json");
        string slotOutput=ValidateOutput(repo,stem+"-slots.json");
        var summary=new{status=failures.Count==0?"PASS_OFFLINE_MATRIX":"FAIL",popSongs=entries.Count,catalogEntries=catalogCount,songJsonFiles=allFiles.Count(f=>f.path.EndsWith(".json",StringComparison.OrdinalIgnoreCase)),
            enabledInstruments=instruments.Select(i=>i.Id),matrixPairs=rows.Count,explicitOffOnBuilds=rows.Count*2,legacyNullChecks=rows.Count,extraPairs=extra.Count,
            drumCombinations=blocked.Count,drumBlockedBuilds=blockedBuilds,assertions,failureAssertions=failures.Count,failedMatrixPairs=rows.Count(r=>r.Failures>0),failedExtraPairs=extra.Count(r=>r.Failures>0),buildExceptions,
            addedRawSourceNotesAcrossPairs=rows.Sum(r=>r.AddedSourceNotes),addedPlannedNotesAcrossPairs=rows.Sum(r=>r.AddedPlannedNotes),
            selectedOriginalKeyOnsets=rows.Sum(r=>r.SelectedKeyOnsets),selectedOriginalKeyOnsetsRetained=rows.Sum(r=>r.SelectedKeyOnsetsRetained),selectedNativeChords=rows.Sum(r=>r.SelectedNativeChords),nativeChordChanges=rows.Sum(r=>r.NativeChordChanges),
            changedSelectedHoldOrSound=rows.Sum(r=>r.ChangedSelectedHoldOrSound),shortenedAddedSustainNotes=rows.Sum(r=>r.ShortenedAddedSustainNotes),extraChangedSelectedHoldOrSound=extra.Sum(r=>r.ChangedSelectedHoldOrSound),extraSelectedKeyOnsets=extra.Sum(r=>r.SelectedKeyOnsets),extraSelectedKeyOnsetsRetained=extra.Sum(r=>r.SelectedKeyOnsetsRetained),supplementaryRawSelectionInspections=slotEvidence.Count,catalogSha256Before=beforeCatalog,catalogSha256After=LibraryCatalog.HashFile(catalog),elapsedMs=watch.Elapsed.TotalMilliseconds,
            coreAssemblyPath=typeof(GameMapping).Assembly.Location,coreAssemblySha256=LibraryCatalog.HashFile(typeof(GameMapping).Assembly.Location),
            nativeKeySendAttempts=0,audioPlayed=false,realGameTested=false,uiTested=false,
            boundary="No native sink, UserData, UI, deployment or input. New notes must be full original source notes; existing mapping may clip plan sound/hold for same-key release. Remaining real rests are not pass targets."};
        WriteNew(output,new{summary,rows,extra,blocked,sourceEvidence,songAndCatalogFiles=allFiles});WriteNew(failureOutput,failures);WriteNew(typicalOutput,typical);WriteNew(slotOutput,slotEvidence);
        var text=new StringBuilder("case,id,instrument,scenario,speed,transpose,tracks,failures,offNotes,onNotes,addedSource,segments,offFirstMs,onFirstMs,offNoteOffGe5s,onNoteOffGe5s,offOnsetGe5s,onOnsetGe5s,retainedKeyOns,totalKeyOns,nativeChanges,offDurationMs,onDurationMs\n");
        foreach(var r in rows.Concat(extra))text.AppendLine(string.Join(",",r.Case,r.Id,r.Instrument,r.Scenario,r.Speed.ToString("R",System.Globalization.CultureInfo.InvariantCulture),r.Transpose,"\""+string.Join(";",r.Tracks??[])+"\"",r.Failures,r.Off.Notes,r.On.Notes,r.AddedSourceNotes,r.InterludeSegments,r.Off.FirstOnsetMs,r.On.FirstOnsetMs,r.Off.InternalNoteOffGapsGe5s,r.On.InternalNoteOffGapsGe5s,r.Off.InternalOnsetGapsGe5s,r.On.InternalOnsetGapsGe5s,r.SelectedKeyOnsetsRetained,r.SelectedKeyOnsets,r.NativeChordChanges,r.Off.DurationMs,r.On.DurationMs));
        WriteTextNew(csv,text.ToString());Console.WriteLine(Serialize(summary));return failures.Count==0?0:1;
    }
}