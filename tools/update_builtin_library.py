"""Add-only score deployment with backed-up, atomic catalogue replacement.
Does not rebuild/replace executables or open actual UserData databases.
"""
import argparse, hashlib, json, os, shutil, sqlite3, stat, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest().upper()
def snapshot(root):
    return {str(p.relative_to(root)).replace('\\','/'):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
def atomic_copy(src,dst):
    temp=dst.with_name('.'+dst.name+'.update-'+uuid.uuid4().hex)
    with src.open('rb') as f,temp.open('xb') as out:
        shutil.copyfileobj(f,out);out.flush();os.fsync(out.fileno())
    # Windows refuses to replace a read-only destination. Change only this backed-up
    # catalogue's write bit for the switch, then restore its original permission bit.
    mode=stat.S_IMODE(dst.stat().st_mode) if dst.exists() else None
    readonly=mode is not None and not (mode & stat.S_IWRITE)
    try:
        if readonly:os.chmod(dst,mode | stat.S_IWRITE)
        os.replace(temp,dst)
    finally:
        if readonly and dst.exists():os.chmod(dst,mode)
def read_catalog(songs):
    catalog=songs/'catalog.db'
    db=sqlite3.connect(catalog.as_uri()+'?mode=ro',uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Corrupt catalogue: '+str(catalog))
        rows=db.execute('SELECT id,relative_path,content_hash,metadata_json FROM entries').fetchall()
    finally:db.close()
    entries={}
    for id_,rel,digest,raw in rows:
        if not rel or Path(rel).name!=rel or '/' in rel or '\\' in rel or not rel.endswith('.json'):
            raise ValueError('Invalid flat score resource path: '+rel)
        p=songs/rel
        if not p.is_file() or sha(p)!=digest.upper():raise ValueError('Catalogue score checksum mismatch: '+rel)
        if id_ in entries:raise ValueError('Duplicate entry: '+id_)
        metadata=json.loads(raw)
        entries[id_]=(rel,digest.upper(),metadata)
    return entries

def validate_update(staged,targets,expected_new=100):
    incoming=read_catalog(staged)
    fresh=[v for k,v in incoming.items() if k.startswith('builtin:pop909-')]
    if len(incoming)!=132 or len(fresh)!=expected_new:raise ValueError('Expected preserved32 + new100 scores')
    titles=[]
    for rel,digest,metadata in fresh:
        prov=metadata.get('provenance',{})
        if not prov.get('artists') or prov.get('synthetic') or prov.get('redistributionVerified') or prov.get('musicReview')!='not-reviewed' or prov.get('gameReview')!='not-tested':
            raise ValueError('Missing identity or misleading review classification: '+rel)
        if prov.get('timingStatus')!='source-compared':raise ValueError('Independent timing comparison missing: '+rel)
        titles.append(metadata['title'])
    if len(set(titles))!=expected_new:raise ValueError('Duplicate new titles')
    operations=[]
    for target in targets:
        old=read_catalog(target)
        for id_,(rel,digest,metadata) in old.items():
            if id_ not in incoming or incoming[id_][0:2]!=(rel,digest):raise ValueError('Would drop/change existing score: '+id_)
            # Preserve published metadata/defaults/IDs as well as score bytes.
            if incoming[id_][2]!=metadata:raise ValueError('Would change existing catalogue metadata: '+id_)
        added=[]
        for id_,(rel,digest,_) in incoming.items():
            p=target/rel
            if p.exists():
                if not p.is_file() or sha(p)!=digest:raise ValueError('Refusing to overwrite existing resource: '+str(p))
            else:added.append(rel)
        operations.append({'target':str(target),'oldEntries':len(old),'newEntries':len(incoming),'addFiles':sorted(added)})
    return incoming,operations

def running_runtime(runtime):
    if os.name!='nt':return []
    cmd="$ErrorActionPreference='Stop'; @(Get-Process -Name QinBan -ErrorAction SilentlyContinue | Select-Object Id,Path) | ConvertTo-Json -Compress"
    r=subprocess.run(['powershell.exe','-NoProfile','-Command',cmd],capture_output=True,text=True,check=True)
    if not r.stdout.strip():return []
    values=json.loads(r.stdout);values=values if isinstance(values,list) else [values]
    return [v for v in values if not v.get('Path') or Path(v['Path']).resolve()==(runtime/'QinBan.exe').resolve()]

def deploy(staged,runtime,source,backup,report,apply=False,check_process=True,resume=False):
    staged,runtime,source,backup,report=map(lambda p:Path(p).resolve(),(staged,runtime,source,backup,report))
    workspace=source.parent.parent
    for p in (staged,runtime,source,backup,report):
        if not p.is_relative_to(workspace) or p==workspace:raise ValueError('All paths must remain in the named workspace')
    if source.name!='Songs' or runtime.parent.name!='dist' or not (runtime/'QinBan.exe').is_file():raise ValueError('Invalid source/runtime target')
    if report.exists() or (backup.exists() and not resume):raise FileExistsError('Refusing to overwrite backup/report')
    if resume and not backup.is_dir():raise FileNotFoundError('Resume requires original backup directory')
    if backup.is_relative_to(runtime) or backup.is_relative_to(source):raise ValueError('Backup must be outside runtime/Songs')
    targets=[runtime/'Songs',source]
    if len(set(targets+[staged]))!=3:raise ValueError('Staging and targets must be distinct')
    incoming,operations=validate_update(staged,targets)
    before=snapshot(runtime)
    report.parent.mkdir(parents=True,exist_ok=True)
    if not apply:
        result={'status':'DRY-RUN-PASS','operations':operations,'runtimeSnapshot':before}
        with report.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        return result
    if check_process and running_runtime(runtime):raise RuntimeError('Close this runtime before updating; no process was stopped')
    if not resume:backup.mkdir(parents=True)
    backed=[];changed=[];added=[]
    try:
        if resume:
            original=json.loads((backup/'before.json').read_text(encoding='utf-8'))
            if original['runtime']!=str(runtime) or original['source']!=str(source):raise ValueError('Backup targets mismatch')
            for rel,digest in original['runtimeSnapshot'].items():
                if before.get(rel)!=digest:raise ValueError('Resume protected resource changed: '+rel)
            before=original['runtimeSnapshot']
        for i,target in enumerate(targets):
            b=backup/('runtime-catalog.db' if i==0 else 'source-catalog.db')
            if resume:
                if not b.is_file() or sha(b)!=sha(target/'catalog.db'):raise ValueError('Resume target catalog differs from original backup')
            else:
                with b.open('xb') as out, (target/'catalog.db').open('rb') as inp:shutil.copyfileobj(inp,out)
            backed.append((target,b))
        if not resume:
            (backup/'before.json').write_text(json.dumps({'runtime':str(runtime),'source':str(source),'runtimeSnapshot':before,'operations':operations},ensure_ascii=False,indent=2),encoding='utf-8')
        for target in targets:
            for rel,digest,metadata in incoming.values():
                p=target/rel
                if not p.exists():
                    with p.open('xb') as out, (staged/rel).open('rb') as inp:shutil.copyfileobj(inp,out)
                    added.append(str(p))
                    if sha(p)!=digest:raise ValueError('Copied resource checksum failed: '+rel)
        for target,b in backed:
            # Recheck immediately before catalogue switch; never switch to incomplete resources.
            for rel,digest,_ in incoming.values():
                if sha(target/rel)!=digest:raise ValueError('Pre-switch resource check failed: '+rel)
            atomic_copy(staged/'catalog.db',target/'catalog.db');changed.append((target,b))
        after=snapshot(runtime)
        bad=[rel for rel,digest in before.items() if rel!='Songs/catalog.db' and after.get(rel)!=digest]
        if bad:raise ValueError('Protected runtime resources changed: '+repr(bad))
        for target in targets:
            actual=read_catalog(target)
            if actual!=incoming:raise ValueError('Post-switch catalogue mismatch')
        result={'status':'PASS','atUtc':datetime.now(timezone.utc).isoformat(),'runtime':str(runtime),
            'backup':str(backup),'operations':operations,'addedFiles':added,'newBuiltinCount':len(incoming),
            'exeUnchanged':before['QinBan.exe']==after['QinBan.exe'],'userDataUnchanged':all(after.get(k)==v for k,v in before.items() if k.startswith('UserData/')),
            'allPreviouslyExistingNonCatalogFilesUnchanged':not bad,'before':before,'after':after,
            'catalogSha256':sha(runtime/'Songs/catalog.db'),'resumedOriginalBackup':resume,'runtimeCatalogReadOnly':not bool(stat.S_IMODE((runtime/'Songs/catalog.db').stat().st_mode)&stat.S_IWRITE),'actualUserDataDatabasesOpened':False,'newDistributionFolderCreated':False}
        with report.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        return result
    except Exception as e:
        rollback=[]
        for target,b in reversed(changed):
            try:atomic_copy(b,target/'catalog.db');rollback.append({'target':str(target),'restored':True})
            except Exception as re:rollback.append({'target':str(target),'restored':False,'error':repr(re)})
        if not report.exists():
            with report.open('x',encoding='utf-8') as f:json.dump({'status':'FAIL','error':repr(e),'rollback':rollback,'newInactiveFilesPreserved':added},f,ensure_ascii=False,indent=2)
        raise

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--staged-songs',required=True);ap.add_argument('--runtime',required=True)
    ap.add_argument('--source-songs',required=True);ap.add_argument('--backup',required=True);ap.add_argument('--report',required=True);ap.add_argument('--apply',action='store_true');ap.add_argument('--resume',action='store_true')
    a=ap.parse_args();r=deploy(a.staged_songs,a.runtime,a.source_songs,a.backup,a.report,a.apply,resume=a.resume)
    print(r['status']+': '+a.runtime)
if __name__=='__main__':main()
