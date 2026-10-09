"""This batch only: apply reviewed, uniform POP909 default key shifts; never edit notes."""
import argparse,copy,json,shutil
from pathlib import Path
from update_builtin_library import read_catalog,sha,snapshot,atomic_copy,running_runtime

def ensure_transpose_only(current,incoming):
    if current.keys()!=incoming.keys():raise ValueError('Entry set changed during key tuning')
    for id_,(rel,digest,old) in current.items():
        newrel,newdigest,new=incoming[id_]
        if (rel,digest)!=(newrel,newdigest):raise ValueError('Key tuning cannot alter source resources')
        expected=copy.deepcopy(old)
        if id_.startswith('builtin:pop909-'):
            shift=new['options']['transpose']
            if isinstance(shift,bool) or not isinstance(shift,int) or not -6<=shift<=6:raise ValueError('Invalid uniform shift')
            expected['options']['transpose']=shift
        if expected!=new:raise ValueError('Only new POP909 options.transpose may change: '+id_)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True,type=Path);ap.add_argument('--runtime',required=True,type=Path);ap.add_argument('--source-songs',required=True,type=Path);ap.add_argument('--backup',required=True,type=Path);ap.add_argument('--report',required=True,type=Path);a=ap.parse_args()
    stage,runtime,source,backup,report=map(lambda p:p.resolve(),(a.stage,a.runtime,a.source_songs,a.backup,a.report));workspace=source.parent.parent
    if any(not p.is_relative_to(workspace) for p in [stage,runtime,source,backup,report]):raise ValueError('Outside intended workspace')
    if not backup.is_dir() or report.exists() or running_runtime(runtime):raise ValueError('Missing original backup, existing report or running app; no processes stopped')
    build=json.loads((stage/'build-report.json').read_text(encoding='utf-8'))
    if not build['status'].startswith('PASS_SOURCE_COMPARED'):raise ValueError('Unverified tuned stage')
    incoming=read_catalog(stage/'Songs');targets=[runtime/'Songs',source]
    if len(incoming)!=132:raise ValueError('Expected existing132; not an expansion')
    for target in targets:ensure_transpose_only(read_catalog(target),incoming)
    before=snapshot(runtime);backed=[];changed=[];audio=[]
    try:
        for i,target in enumerate(targets):
            b=backup/('runtime-before-key-defaults.db' if i==0 else 'source-before-key-defaults.db')
            with (target/'catalog.db').open('rb') as f,b.open('xb') as out:shutil.copyfileobj(f,out)
            backed.append((target,b))
        for target,b in backed:atomic_copy(stage/'Songs/catalog.db',target/'catalog.db');changed.append((target,b))
        initial=stage.parent/'reviewed'
        for item in build['waves']:
            new=stage/item['relativePath'];dest=runtime/'试听音频'/new.name;old=initial/item['relativePath']
            if sha(dest)!=sha(old):raise ValueError('Refusing to replace a user-modified generated audition')
            audio.append((dest,old));atomic_copy(new,dest)
        after=snapshot(runtime);allowed={'Songs/catalog.db'}|{str(p.relative_to(runtime)).replace('\\','/') for p,_ in audio}
        bad=[rel for rel,digest in before.items() if rel not in allowed and after.get(rel)!=digest]
        if bad:raise ValueError('Protected files changed: '+repr(bad))
        for target in targets:
            if read_catalog(target)!=incoming:raise ValueError('Final tuned catalogue mismatch')
        r={'status':'PASS_DEFAULT_KEY_TUNING','onlyNewPop909DefaultTransposeChanged':True,'sourceNotesAndTimingUnchanged':True,'exeAndUserDataUnchanged':not bad,
           'catalogSha256':sha(runtime/'Songs/catalog.db'),'newBuiltinCount':132,'sampleIds':build['sampleIds'],'before':before,'after':after,'generatedAuditionsUpdated':len(audio),
           'backups':[str(b) for _,b in backed],'noNewDistributionDirectory':True,'realGameTested':False}
    except Exception as e:
        for dest,old in audio:atomic_copy(old,dest)
        for target,b in reversed(changed):atomic_copy(b,target/'catalog.db')
        r={'status':'FAIL_TUNING_ROLLED_BACK','error':repr(e)}
        with report.open('x',encoding='utf-8') as f:json.dump(r,f,ensure_ascii=False,indent=2)
        raise
    with report.open('x',encoding='utf-8') as f:json.dump(r,f,ensure_ascii=False,indent=2)
    print('PASS: same directory132; key defaults only; old32/exe/UserData untouched')
if __name__=='__main__':main()
