"""Local-only audit of evidence completeness. Does not acquire, distribute or certify rights.
Evidence JSON decisions are human declarations; audit success is NOT legal/music approval.
"""
import argparse, csv, hashlib, json, math, re, struct, sys
from collections import defaultdict
from datetime import datetime
from smf_reference import parse_smf
from pathlib import Path

REQUIRED = ('work_id','edition_id','title','artist','provider','platform_ids','source_url','license','completeness',
            'source_file','source_sha256','normalized_file','timing_report','rights_review','music_review','game_review')

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_EDITIONS = 10_000
MAX_NOTES = 100_000
MAX_DURATION_MS = 1_800_000
TIMING_TOLERANCE_MS = .0021
DATA_ERRORS = (ValueError, KeyError, TypeError, OSError, RecursionError, OverflowError, IndexError, RuntimeError, struct.error, csv.Error)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest().upper()


def resolve(root, relative):
    root = root.resolve()
    if not isinstance(relative,str) or not relative.strip() or Path(relative).is_absolute(): raise ValueError('evidence must be a nonempty relative path')
    path = (root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('missing evidence or path outside intake root')
    if path.stat().st_size>MAX_FILE_BYTES: raise ValueError('individual intake evidence exceeds 16 MiB')
    return path



def text(value, limit=4096):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=limit


def number(value):
    # bool is an int subclass, but not a valid musical number.
    return type(value) is int or (type(value) is float and math.isfinite(value))


def integer(value, low, high):
    return type(value) is int and low<=value<=high


def sha256(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',value):
        raise ValueError('expected a 64-digit SHA256')
    return value.upper()


def json_object(pairs):
    result = {}
    for key,value in pairs:
        key = key.casefold()
        if key in result: raise ValueError('duplicate JSON property: '+key)
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(value): raise ValueError('non-finite JSON number: '+value)
    data = json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=json_object,parse_constant=invalid_constant)
    pending = [(data,0)]
    while pending:
        value,depth = pending.pop()
        if isinstance(value,(dict,list)):
            if depth>=32: raise ValueError('JSON exceeds depth 32')
            pending.extend((v,depth+1) for v in (value.values() if isinstance(value,dict) else value))
        elif type(value) is float and not math.isfinite(value): raise ValueError('non-finite JSON number')
    if not isinstance(data,dict): raise ValueError('JSON top level must be an object')
    return data


def non_synthetic(data):
    if type(data.get('synthetic',False)) is not bool: raise ValueError('synthetic must be a boolean')
    if data.get('synthetic',False): raise ValueError('synthetic fixtures are never golden works')


def validate_notes(data, require_length=True):
    notes = data.get('notes')
    if not isinstance(notes,list) or not 1<=len(notes)<=MAX_NOTES:
        raise ValueError('notes must contain 1-100,000 note objects')
    events = []
    for index,note in enumerate(notes):
        if not isinstance(note,dict) or not {'pitch','startms','durationms'}<=note.keys():
            raise ValueError(f'notes[{index}]: pitch/startMs/durationMs required')
        pitch,start,duration = note['pitch'],note['startms'],note['durationms']
        track,velocity,percussion = note.get('track',0),note.get('velocity',90),note.get('percussion',False)
        if not integer(pitch,0,127) or not integer(track,0,1023) or not integer(velocity,1,127) or type(percussion) is not bool:
            raise ValueError(f'notes[{index}]: invalid pitch/track/velocity/percussion')
        if not number(start) or not number(duration) or not 0<=start<=MAX_DURATION_MS or not 0<duration<=60_000 or start+duration>MAX_DURATION_MS:
            raise ValueError(f'notes[{index}]: invalid finite onset/duration or 30-minute budget')
        events.append((track,pitch,velocity,percussion,float(start) if start else 0.0,float(duration)))
    end = max(n[4]+n[5] for n in events)
    length = data.get('lengthms',None if require_length else 0)
    if not number(length) or not 0<=length<=MAX_DURATION_MS: raise ValueError('invalid finite lengthMs or 30-minute budget')
    if require_length and (length<=0 or end>length+TIMING_TOLERANCE_MS):
        raise ValueError('full lengthMs must be positive and cover every note')
    events.sort(key=lambda n:(n[0],n[4],n[1],n[5],n[2],n[3]))
    return dict(notes=events,length=float(length) if require_length else float(max(length,end)))



def utf16_length(value):
    # Match C# string.Length; only the new identity-field budgets use this helper.
    return len(value.encode('utf-16-le', 'surrogatepass')) // 2


def validate_identity_metadata(provenance, required=False):
    artists = provenance.get('artists', [])
    if not isinstance(artists, list) or len(artists) > 32 or any(not isinstance(v,str) or not v.strip() or utf16_length(v)>256 for v in artists):
        raise ValueError('invalid singer artists list')
    if len({v.strip().casefold() for v in artists}) != len(artists): raise ValueError('duplicate singer artists')
    languages = provenance.get('languagetags', [])
    if not isinstance(languages, list) or len(languages) > 16 or any(not isinstance(v,str) or utf16_length(v)>256 or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*',v) for v in languages):
        raise ValueError('invalid languageTags list; syntax only, not registered language certification')
    if len({v.casefold() for v in languages}) != len(languages): raise ValueError('duplicate languageTags')
    for field, limit in [('album', 1000), ('versionlabel', 256)]:
        if field in provenance and (not isinstance(provenance[field],str) or utf16_length(provenance[field])>limit): raise ValueError('invalid metadata: '+field)
    if required:
        if not artists and not text(provenance.get('artist'), 4096): raise ValueError('formal normalized score requires singer identity (artists or legacy artist)')
        if not languages or any(v.split('-')[0].lower() == 'und' for v in languages): raise ValueError('formal normalized score requires stated languageTags; und/unknown is not complete identity')


def validate_score(song, normalized=True):
    if 'songnotes' in song: raise ValueError('version=1 notes required; songNotes is not normalized')
    if not integer(song.get('version',None if normalized else 1),1,1): raise ValueError('normalized score must have version=1')
    for key,limit in [('title',180),('author',180),('category',80),('description',8000),('source',1000)]:
        if key in song and (not isinstance(song[key],str) or len(song[key])>limit or (key=='title' and not song[key].strip())):
            raise ValueError('invalid score metadata: '+key)
    instrument=song.get('keyinstrumentid','windsong')
    if instrument not in ('windsong','floral','vintage','horn','ukulele','euphonia','piano','harmonic','voice','arataki','qiyan','djem'):
        raise ValueError('unknown keyInstrumentId in version=1 score')
    bpm=song.get('bpm',100)
    if not number(bpm) or not 20<=bpm<=400: raise ValueError('BPM must be finite and within 20-400')
    warnings=song.get('warnings',[])
    if not isinstance(warnings,list) or len(warnings)>100 or any(not isinstance(w,str) or len(w)>3000 for w in warnings):
        raise ValueError('invalid warnings list')
    provenance=song.get('provenance',{})
    if not isinstance(provenance,dict): raise ValueError('provenance must be an object')
    non_synthetic(song);non_synthetic(provenance)
    for key in ('workid','editionid','artist','provider','sourceurl','license','licenseurl','sourcesha256','notationsha256',
                'maintainer','completeness','timingstatus','musicreview','gamereview'):
        if key in provenance and (not isinstance(provenance[key],str) or len(provenance[key])>4096):
            raise ValueError('invalid provenance metadata: '+key)
    for key in ('aliases','tags'):
        values=provenance.get(key,[])
        if not isinstance(values,list) or len(values)>100 or any(not isinstance(v,str) or len(v)>256 for v in values):
            raise ValueError('invalid provenance list: '+key)
    if 'redistributionverified' in provenance and type(provenance['redistributionverified']) is not bool:
        raise ValueError('redistributionVerified must be a boolean, not certification')
    retrieved=provenance.get('retrievedat')
    if retrieved is not None:
        if not text(retrieved): raise ValueError('retrievedAt must be an ISO timestamp or null')
        datetime.fromisoformat(retrieved.replace('Z','+00:00'))
    validate_identity_metadata(provenance, required=normalized)
    return validate_notes(song,require_length=normalized)


def compare(left, right):
    if len(left['notes'])!=len(right['notes']): raise ValueError('reference note count mismatch')
    error=abs(left['length']-right['length'])
    for index,(a,b) in enumerate(zip(left['notes'],right['notes'])):
        if a[:4]!=b[:4]: raise ValueError(f'reference pitch/track/velocity/percussion mismatch at event {index}')
        error=max(error,abs(a[4]-b[4]),abs(a[5]-b[5]))
    if error>TIMING_TOLERANCE_MS: raise ValueError('reference onset/duration/total length mismatch')
    return error


def source_score(path):
    if path.suffix.lower() in ('.mid','.midi'):
        parsed=parse_smf(path.read_bytes())
        return validate_notes({'lengthms':parsed['lengthMs'],'notes':[
            {key.casefold():value for key,value in note.items()} for note in parsed['notes']]})
    if path.suffix.lower()=='.json': return validate_score(read_json(path),normalized=False)
    raise ValueError('source must be local MIDI or version=1 notes JSON')


def validate_review(evidence, field, row, binding, length):
    if evidence.get('decision')!='approved' or any(not text(evidence.get(k)) for k in ('reviewer','reviewedat','notes')):
        raise ValueError('missing explicit human review declaration')
    datetime.fromisoformat(evidence['reviewedat'].replace('Z','+00:00'))
    if sha256(evidence.get('sha256'))!=binding: raise ValueError('decision is not bound to reviewed bytes')
    if evidence.get('workid')!=row['work_id']: raise ValueError('review workId scope must match work_id')
    if field!='rights_review' or 'editionid' in evidence:
        if evidence.get('editionid')!=row['edition_id']: raise ValueError('review editionId scope must match edition_id')
    if field=='rights_review':
        permissions=evidence.get('permissions')
        if not isinstance(permissions,list) or any(not text(v) for v in permissions) or not {'normalize','arrange','bundle'}<=set(permissions):
            raise ValueError('rights review must list conversion, arrangement and bundling permissions')
    elif field=='music_review':
        reviewed_length=evidence.get('reviewedlengthms')
        if evidence.get('completeness')!='full-work' or not number(reviewed_length) or not 0<reviewed_length<=MAX_DURATION_MS or abs(reviewed_length-length)>TIMING_TOLERANCE_MS:
            raise ValueError('music review must cover full-work and the complete reviewedLengthMs')
    else:
        options=evidence.get('playoptions')
        if not text(evidence.get('instrumentid')) or not text(evidence.get('gameversion')) or not isinstance(options,dict):
            raise ValueError('game review requires instrumentId/gameVersion/playOptions')
        if 'instrumentid' in options and options['instrumentid']!=evidence['instrumentid']:
            raise ValueError('game review target and playOptions instrumentId mismatch')


def reject(row, error):
    if error not in row['errors']: row['errors'].append(error)
    row['status']='REJECT'


def report(rows, fatal_errors):
    rejected=[row for row in rows if row['status']=='REJECT']
    complete=[row for row in rows if row['status']=='EVIDENCE_COMPLETE']
    return dict(candidateEditions=len(rows),evidenceCompleteEditions=len(complete),
                evidenceCompleteDistinctWorks=len({r['workId'] for r in complete}),rejectedEditions=len(rejected),
                certification='administrative completeness only; human decisions not independently certified; no files copied into Songs',
                fatalErrors=fatal_errors,rejectedRows=rejected,rows=rows)



def audit(manifest, root):
    rows=[];candidates=[];fatal_errors=[];editions=defaultdict(list)
    try:
        root=root.resolve()
        if manifest.stat().st_size>MAX_FILE_BYTES: raise ValueError('manifest exceeds 16 MiB')
        with manifest.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream,strict=True)
            if tuple(reader.fieldnames or ())!=REQUIRED: raise ValueError('Unexpected manifest columns')
            for line,row in enumerate(reader,start=2):
                if len(rows)>=MAX_EDITIONS: raise ValueError('Pilot intake over 10,000 editions; split into reviewed batches')
                result=dict(line=line,workId=row.get('work_id') or '',editionId=row.get('edition_id') or '',status='EVIDENCE_COMPLETE',errors=[])
                rows.append(result)
                if text(row.get('edition_id')): editions[row['edition_id']].append(result)
                stage='metadata'
                try:
                    if None in row or any(not text(row.get(k)) for k in REQUIRED): raise ValueError('missing, extra or overlong metadata')
                    platforms=[v.strip() for v in row['platform_ids'].split(';')]
                    if any(not v for v in platforms) or len(set(platforms))!=len(platforms): raise ValueError('platform_ids must contain distinct nonempty stable identities')
                    if row['completeness']!='full-work': raise ValueError('fragments/exercises do not qualify as full works')
                    if row['license'].strip().lower() in ('unverified','unknown'): raise ValueError('license is unverified')
                    if not row['source_url'].startswith(('https://','http://')): raise ValueError('traceable source URL required')
                    stage='source_file';source=resolve(root,row['source_file']);source_hash=digest(source)
                    if source_hash!=sha256(row['source_sha256']): raise ValueError('source hash mismatch')
                    actual_source=source_score(source)
                    stage='normalized_file';normalized=resolve(root,row['normalized_file']);normalized_hash=digest(normalized)
                    song=read_json(normalized);actual_normalized=validate_score(song);provenance=song.get('provenance',{})
                    if sha256(provenance.get('sourcesha256'))!=source_hash or provenance.get('timingstatus')!='source-compared':
                        raise ValueError('normalized source/timing claim not bound to source')
                    for key,field in [('workid','work_id'),('editionid','edition_id')]:
                        if provenance.get(key) and provenance[key]!=row[field]: raise ValueError('normalized provenance identity mismatch: '+key)
                    stage='timing_report';timing=read_json(resolve(root,row['timing_report']))
                    if timing.get('status')!='PASS' or sha256(timing.get('sourcesha256'))!=source_hash or sha256(timing.get('normalizedsha256'))!=normalized_hash:
                        raise ValueError('missing hash-bound timing PASS report')
                    stage='referenceFile';reference_path=resolve(root,timing.get('referencefile'))
                    if sha256(timing.get('referencesha256'))!=digest(reference_path): raise ValueError('reference hash mismatch')
                    reference=read_json(reference_path);non_synthetic(reference);actual_reference=validate_notes(reference)
                    compare(actual_source,actual_reference);error=compare(actual_normalized,actual_reference);compare(actual_source,actual_normalized)
                    stage='timing_report';declared_error=timing.get('maxerrorms')
                    if not number(declared_error) or not 0<=declared_error<=TIMING_TOLERANCE_MS or not integer(timing.get('notes'),1,MAX_NOTES) or timing['notes']!=len(actual_normalized['notes']):
                        raise ValueError('invalid timing tolerance/note count')
                    if abs(declared_error-error)>1e-9: raise ValueError('maxErrorMs does not match actual normalized/reference comparison')
                    for field in ('rights_review','music_review','game_review'):
                        stage=field;evidence=read_json(resolve(root,row[field]))
                        validate_review(evidence,field,row,source_hash if field=='rights_review' else normalized_hash,actual_normalized['length'])
                    fingerprint=hashlib.sha256(json.dumps(actual_normalized,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
                    source_fingerprint=hashlib.sha256(json.dumps(actual_source,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
                    candidates.append(dict(row=result,source=source_hash,normalized=normalized_hash,content=fingerprint,sourceContent=source_fingerprint,platforms=platforms))
                except DATA_ERRORS as ex: reject(result,stage+': '+str(ex))
    except DATA_ERRORS as ex:
        fatal_errors.append('manifest: '+str(ex))
        for result in rows: reject(result,'batch rejected: manifest error')
    for group in editions.values():
        if len(group)>1:
            for result in group: reject(result,'duplicate edition_id')
    for field in ('source','normalized','content','sourceContent','platforms'):
        groups=defaultdict(list)
        for candidate in candidates:
            for key in (candidate[field] if field=='platforms' else [candidate[field]]): groups[key].append(candidate['row'])
        for group in groups.values():
            if len({r['workId'] for r in group})>1:
                for result in group: reject(result,'conflicting work_id for same '+field+' identity')
    arrangements=set()
    for candidate in candidates:
        keys={(candidate['row']['workId'],field,candidate[field]) for field in ('content','sourceContent')}
        if keys & arrangements: reject(candidate['row'],'duplicate arrangement; byte/metadata changes do not add an edition')
        arrangements.update(keys)
    return report(rows,fatal_errors)



def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('intake_root',type=Path);parser.add_argument('new_report',type=Path);args=parser.parse_args()
    if args.new_report.exists():
        print('FAIL: Refusing to overwrite report',file=sys.stderr);return 1
    result=audit(args.manifest,args.intake_root)
    try:
        args.new_report.parent.mkdir(parents=True,exist_ok=True)
        with args.new_report.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
    except OSError as ex:
        print('FAIL: could not create new report: '+str(ex),file=sys.stderr);return 1
    print(f"AUDIT {result['candidateEditions']} editions; evidence-complete distinct works {result['evidenceCompleteDistinctWorks']}; rejected {result['rejectedEditions']}. Not automatic rights/music certification.")
    for error in result['fatalErrors']: print('FAIL: '+error)
    for row in result['rejectedRows']:
        print(f"REJECT line {row['line']} {row['workId']}/{row['editionId']}: "+'; '.join(row['errors']))
    return 1 if result['rejectedEditions'] or result['fatalErrors'] else 0


if __name__=='__main__': raise SystemExit(main())
