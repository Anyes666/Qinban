"""Only the backed-up executable + a NEW feature document; never touch UserData/Songs.
Run a preflight first. Unknown/running QinBan paths fail closed. No process termination.
"""
import argparse, json, os, shutil, subprocess
from pathlib import Path
from update_builtin_library import atomic_copy, sha, snapshot

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
BATCH = REPO / '.validation/smart-interludes-2026-10-06'
RUNTIME = WORKSPACE / 'dist/QinBan-0.4.2-two-song-pilot-win-x64'
BACKUP = WORKSPACE / '.Codex/backups/smart-interludes-2026-10-06'

def active_instances():
    if os.name != 'nt': raise RuntimeError('Deployment requires this Windows host')
    command = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $ErrorActionPreference='Stop'; $r=@(Get-Process -Name QinBan -ErrorAction SilentlyContinue | Select-Object Id,Path); if($r.Count -eq 0){'[]'}else{ConvertTo-Json -InputObject $r -Compress}"
    run = subprocess.run(['powershell.exe','-NoProfile','-Command',command], capture_output=True,
        encoding='utf-8', errors='strict', check=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    values = json.loads(run.stdout); values = values if isinstance(values,list) else [values]
    # Conservatively guard all QinBan instances, including elevated processes whose path is hidden.
    return values

def verify_inputs():
    stage = BATCH / 'publish/QinBan.exe'; original = BACKUP / 'QinBan-before-smart-interludes.exe'
    document = REPO / 'SMART-INTERLUDES.md'
    for path in [stage, original, document, RUNTIME / 'QinBan.exe']:
        if not path.resolve().is_relative_to(WORKSPACE.resolve()) or not path.is_file():
            raise ValueError('Missing or out-of-workspace input: ' + str(path))
    if sha(original) != sha(RUNTIME / 'QinBan.exe'): raise ValueError('Installed executable changed since backup; refusing overwrite')
    if sha(stage) == sha(original): raise ValueError('Staged executable does not contain a new build')
    before = json.loads((BACKUP / 'before.json').read_text(encoding='utf-8'))
    # Original score resources/catalogue must remain byte-for-byte intact.
    for path, digest in before.items():
        if '/Songs/' in path.replace('\\','/') and sha(Path(path)) != digest: raise ValueError('A protected score/catalogue changed: ' + path)
    if (RUNTIME / '智能衔接说明.md').exists(): raise ValueError('Refusing to overwrite an existing feature document')
    return stage, original, document

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', required=True, type=Path); args = parser.parse_args()
    report = args.report.resolve()
    if not report.is_relative_to(BATCH.resolve()) or report.exists(): raise ValueError('Use a NEW report in the current validation batch')
    stage, original, document = verify_inputs(); active = active_instances()
    result = {'status':'BLOCKED_RUNNING_QINBAN' if active else 'PREFLIGHT_READY',
        'runningInstances':active, 'runtime':str(RUNTIME), 'oldExeSha256':sha(original), 'newExeSha256':sha(stage),
        'newDistributionDirectory':False, 'userDataModified':False, 'songsModified':False, 'gameInputSent':False}
    if args.apply and not active:
        before = snapshot(RUNTIME); applied = False; doc = RUNTIME / '智能衔接说明.md'
        try:
            # Race check immediately before switching; a new instance or a locked EXE prevents replace.
            if active_instances(): raise RuntimeError('QinBan started after preflight; no replacement attempted')
            atomic_copy(stage, RUNTIME / 'QinBan.exe'); applied = True
            with document.open('rb') as source, doc.open('xb') as target: shutil.copyfileobj(source,target)
            after = snapshot(RUNTIME)
            unexpected = [rel for rel,digest in before.items() if rel != 'QinBan.exe' and after.get(rel) != digest]
            if unexpected or sha(RUNTIME / 'QinBan.exe') != sha(stage): raise RuntimeError('Protected deployment check failed: ' + repr(unexpected))
            result.update(status='PASS_IN_PLACE_UPDATE', protectedFilesChecked=len(before), protectedFilesChanged=unexpected,
                featureDocument=str(doc), backup=str(original), before=before, after=after)
        except Exception as error:
            if applied: atomic_copy(original, RUNTIME / 'QinBan.exe')
            result.update(status='FAILED_ROLLED_BACK' if applied else 'FAILED_NO_EXE_CHANGE', error=repr(error))
            with report.open('x',encoding='utf-8') as file: json.dump(result,file,ensure_ascii=False,indent=2)
            raise
    with report.open('x',encoding='utf-8') as file: json.dump(result,file,ensure_ascii=False,indent=2)
    print(result['status'])
    return 3 if active and args.apply else 0
if __name__ == '__main__': raise SystemExit(main())
