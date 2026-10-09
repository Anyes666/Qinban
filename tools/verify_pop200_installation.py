"""Read-only post-install check; independent of installer PASS flags.
Protect original runtime/UserData/score files and prove the installed332 catalogue.
"""
import argparse,hashlib,json,sqlite3,stat
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.validation/pop200-2026-10-06'

def sha(p):
    if p.is_symlink() or p.stat().st_file_attributes & 0x400:raise ValueError('Reparse path refused: '+str(p))
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest().upper() if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read()).hexdigest().upper()
def snapshot(root):
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
def rows(root):
    c=sqlite3.connect((root/'catalog.db').as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        if c.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('SQLite integrity failed')
        columns=[v[1] for v in c.execute('PRAGMA table_info(entries)')]
        result={v[0]:v for v in c.execute('SELECT * FROM entries ORDER BY id')}
        raw={v[0]:v[1] for v in c.execute('SELECT id,metadata_json FROM entries')}
        return columns,result,raw
    finally:c.close()

def verify():
    manifest=json.loads((ROOT/'catalog-intake/pop200-2026-10-06-v2/manifest.json').read_text(encoding='utf8'))
    stage=RUN/'stage/Songs';stage_hashes=snapshot(stage)
    newcomers={'pop909-'+s['id']+'.json' for s in manifest['songs']}
    if len(newcomers)!=200:raise ValueError('Expected actual200 new resources')
    stage_columns,stage_rows,stage_raw=rows(stage)
    old_columns,old_rows,old_raw=rows(RUN/'baseline-Songs')
    if len(stage_rows)!=332 or len(old_rows)!=132:raise ValueError('Invalid baseline/stage count')
    locations=[]
    for name,label,catalog_relative,prefix in [('runtime-before','runtime','Songs/catalog.db','Songs/'),('source-songs-before','source','catalog.db','')]:
        before=json.loads((RUN/(name+'.json')).read_text(encoding='utf8'));root=Path(before['root'])
        original={p['relativePath']:p['sha256'] for p in before['files']}
        expected=dict(original);expected[catalog_relative]=stage_hashes['catalog.db']
        for relative in newcomers:expected[prefix+relative]=stage_hashes[relative]
        current=snapshot(root)
        if current!=expected:raise ValueError('Installed delta not exactly200 additions plus catalogue: '+label)
        target=root/'Songs' if label=='runtime' else root
        columns,actual,raw=rows(target)
        if columns!=stage_columns or actual!=stage_rows:raise ValueError('Installed catalogue not exact validated stage: '+label)
        if not all(raw.get(identity)==text for identity,text in old_raw.items()):raise ValueError('Original132 metadata/defaults/IDs changed: '+label)
        if any((target/('catalog.db'+s)).exists() for s in ['-wal','-shm','-journal']):raise ValueError('Unexpected catalogue sidecar')
        locations.append({'label':label,'root':str(root),'catalogEntries':len(actual),'newResources':len(newcomers),'oldMetadataByteExactChecks':len(old_raw),'protectedOriginalNonCatalogFiles':len(original)-1,'protectedNonCatalogBytesUnchanged':True,'catalogSha256':sha(target/'catalog.db')})
    protected=json.loads((RUN/'app-sources-protected.json').read_text(encoding='utf8'))
    if any(sha(Path(e['path']))!=e['sha256'] for e in protected):raise ValueError('Application source mutated')
    return {'status':'PASS_INSTALLED332_INDEPENDENT_DELTA','locations':locations,'appSourceHashesUnchanged':len(protected),'exeUnchanged':True,'userDataUnchanged':True,'old132ScoreBytesAndRawMetadataUnchanged':True,'new200FilesEqualValidatedStage':True,'nativeKeySendAttempts':0,'actualUserDataDatabasesOpened':False,'gameTested':False,'musicReviewed':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    out=a.report.absolute()
    if out.exists() or not out.is_relative_to(RUN):raise ValueError('Use a NEW report under this validation run')
    result=verify()
    with out.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(result['status']+'; old132/EXE/UserData exact; new200 installed in both original locations; native=0')

if __name__=='__main__':main()
