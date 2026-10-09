"""Exercise the real strict200 converter CLI against deterministic negative inputs.
All outputs are NEW isolated evidence, not production. Expected rejections are retained.
"""
import copy,hashlib,json,os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.validation/pop200-2026-10-06'
DOTNET=ROOT.parent/'.tools/dotnet/dotnet.exe'
TOOL=RUN/'artifacts/bin/Pop200Tool/release/Pop200Tool.dll'
INTAKE=ROOT/'catalog-intake/pop200-2026-10-06-v2'
BASE=RUN/'baseline-Songs'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def state(root):return {p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file()}
def write(p,v):
    with p.open('x',encoding='utf8') as f:json.dump(v,f,ensure_ascii=False,indent=2)

def main():
    out=RUN/'conversion-negative';out.mkdir(exist_ok=False)
    original=json.loads((INTAKE/'build-manifest.json').read_text(encoding='utf8'))
    before=state(BASE);stage_before=state(RUN/'stage');results=[]
    env=dict(os.environ,DOTNET_CLI_HOME=str(RUN/'build-home/cli'),DOTNET_NOLOGO='1',DOTNET_CLI_TELEMETRY_OPTOUT='1',TEMP=str(RUN/'build-home/tmp'),TMP=str(RUN/'build-home/tmp'))
    def reject(name,manifest=None,baseline=BASE,target=None,partial=False):
        value=copy.deepcopy(original) if manifest is None else manifest
        file=out/(name+'-manifest.json');write(file,value)
        target=out/(name+'-output') if target is None else target
        command=[str(DOTNET),str(TOOL),'build',str(file),str(baseline),str(target)]
        run=subprocess.run(command,capture_output=True,encoding='utf8',env=env,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/(name+'.stdout.log')).write_text(run.stdout,encoding='utf8');(out/(name+'.stderr.log')).write_text(run.stderr,encoding='utf8')
        if run.returncode==0:raise AssertionError('Accepted invalid input: '+name)
        if partial:
            report=json.loads((target/'build-report.json').read_text(encoding='utf8'))
            if report['status']!='FAILED_PARTIAL_OUTPUT_RETAINED_DO_NOT_PUBLISH' or (target/'Songs/catalog.db').exists():raise AssertionError('Partial converter output falsely publishable')
        elif target != RUN/'stage' and target.exists():raise AssertionError('Preflight failure created an output directory: '+name)
        results.append({'name':name,'status':'PASS_EXPECTED_REJECTION','exitCode':run.returncode,'command':command,'stderrPath':str(out/(name+'.stderr.log')),'partialRetained':partial})
    reject('existing-output',target=RUN/'stage')
    value=copy.deepcopy(original);value['songs']=value['songs'][:199];reject('count-not200',value)
    value=copy.deepcopy(original);value['songs'][1]['id']=value['songs'][0]['id'];reject('duplicate-id',value)
    value=copy.deepcopy(original);value['songs'][0]['sourceSha256']='0'*64;reject('bad-source-hash',value)
    value=copy.deepcopy(original);value['inventedApproval']='PASS';reject('unknown-schema-field',value)
    value=copy.deepcopy(original);value['retrievedAtUtc']='2026-10-06T12:00:00+08:00';reject('non-utc-time',value)
    reject('baseline-not132',baseline=ROOT/'.validation/pop100-baseline-2026-10-06/source-snapshot/Songs')
    value=copy.deepcopy(original);first=min(value['songs'],key=lambda s:s['id'])
    ref=json.loads(Path(first['referencePath']).read_text(encoding='utf8'));ref['notes'][0]['startMs']+=25
    ref_path=out/'bad-onset-reference.json';write(ref_path,ref);first['referencePath']=str(ref_path)
    reject('independent-reference-onset-mismatch',value,partial=True)
    if before != state(BASE) or stage_before != state(RUN/'stage'):raise AssertionError('Existing validated stage/baseline mutated')
    report={'status':'PASS_CONVERTER_NEGATIVE_TESTS','cases':len(results),'failures':0,'baselineUnchanged':True,'stageUnchanged':True,'nativeKeySendAttempts':0,'results':results}
    write(RUN/'converter-negative-tests.json',report)
    print('PASS converter negative CLI: '+str(len(results))+' expected rejections, old stage/baseline unchanged, native=0')

if __name__=='__main__':main()
