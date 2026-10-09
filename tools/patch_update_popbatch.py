from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'tools'/'update_popbatch_library.py'
s=path.read_text(encoding='utf8')
s=s.replace('"""Fixed POP200 add-only update: 132 -> 332, for the existing local library.\n\nPreflight is the default; --apply is explicit. Only 200 NEW score files per\nlocation and the two backed-up catalogues may be installed. UserData is hashed,', '"""Generic add-only update for a validated source batch and the existing local library.\n\nPreflight is the default; --apply is explicit. Only the NEW score files in the\nstaged catalogue and the two backed-up catalogues may be installed. UserData is hashed,')
s=s.replace('OLD_COUNT = 132\nNEW_COUNT = 200\nFINAL_COUNT = 332\n', '')
s=s.replace("    if (prov.get('synthetic') is not False or prov.get('redistributionVerified') is not False or\n            prov.get('musicReview') != 'not-reviewed' or prov.get('gameReview') != 'not-tested' or\n            prov.get('timingStatus') != 'source-compared' or prov.get('provider') != 'POP909'):", "    if (prov.get('synthetic') is not False or prov.get('redistributionVerified') is not False or\n            prov.get('musicReview') != 'not-reviewed' or prov.get('gameReview') != 'not-tested' or\n            prov.get('timingStatus') != 'source-compared' or prov.get('provider') != 'POP909'):")
anchor="""    source_hash = _digest(prov.get('sourceSha256'), rel + ' source')
    sid = match[1]
"""
replacement="""    work_id = prov.get('workId')
    edition_id = prov.get('editionId')
    version_label = prov.get('versionLabel')
    if not isinstance(work_id, str) or not work_id.strip() or not isinstance(edition_id, str) or not edition_id.strip():
        raise ValueError('New entries require nonempty workId and editionId: ' + rel)
    if not isinstance(version_label, str):
        raise ValueError('New entries require string versionLabel: ' + rel)
    source_hash = _digest(prov.get('sourceSha256'), rel + ' source')
    sid = match[1]
"""
if anchor not in s: raise SystemExit('validate new anchor not found')
s=s.replace(anchor,replacement)
start=s.index('def validate_update(staged, targets):')
end=s.index('\ndef active_instances():',start)
new_func='''def validate_update(staged, targets):
    incoming = read_catalog(staged)
    old_catalogs = [read_catalog(target) for target in targets]
    if len(old_catalogs) != 2:
        raise ValueError('Exactly runtime and source catalogues are required')
    old_count = len(old_catalogs[0].entries)
    final_count = len(incoming.entries)
    if old_count <= 0 or any(len(old.entries) != old_count for old in old_catalogs):
        raise ValueError('Runtime/source original catalogue counts differ or are empty')
    if final_count <= old_count:
        raise ValueError('Stage must strictly add entries over the existing baseline')
    baseline = old_catalogs[0]
    for old in old_catalogs:
        if (old.columns != incoming.columns or old.search_columns != incoming.search_columns or
                old.meta_rows != incoming.meta_rows):
            raise ValueError('Would change original catalogue schema/classification')
        if old.rows != baseline.rows or old.search_rows != baseline.search_rows:
            raise ValueError('Runtime/source original catalogue entries differ')
        for id_, row in old.rows.items():
            if incoming.rows.get(id_) != row:
                raise ValueError('Would drop/change existing score/metadata/defaults/ID: ' + id_)
            if old.search_rows and incoming.search_rows.get(id_) != old.search_rows[id_]:
                raise ValueError('Would change existing search metadata: ' + id_)
    new_ids = sorted(set(incoming.entries) - set(baseline.entries))
    expected_new = final_count - old_count
    if len(new_ids) != expected_new:
        raise ValueError('Stage delta does not equal final minus baseline entries')
    old_title_work = {}
    old_source_hashes = set()
    for entry in baseline.entries.values():
        title = _title_key(entry[2].get('title'))
        prov = entry[2].get('provenance') or {}
        old_title_work.setdefault(title, set()).add(prov.get('workId'))
        source = prov.get('sourceSha256')
        if isinstance(source, str) and source:
            old_source_hashes.add(source.upper())
    new_titles = {}
    new_editions = set()
    new_source_hashes = set()
    for id_ in new_ids:
        entry = incoming.entries[id_]
        _validate_new(id_, entry, incoming.rows[id_], incoming.columns, staged)
        title = _title_key(entry[2].get('title'))
        prov = entry[2]['provenance']
        work_id = prov['workId']
        version_label = prov.get('versionLabel', '').strip()
        edition_id = prov['editionId']
        source_hash = prov['sourceSha256'].upper()
        if edition_id in new_editions or edition_id in {e[2].get('provenance', {}).get('editionId') for e in baseline.entries.values()}:
            raise ValueError('Duplicate editionId: ' + edition_id)
        if source_hash in old_source_hashes or source_hash in new_source_hashes:
            raise ValueError('Duplicate source SHA cannot create another edition: ' + title)
        if title in old_title_work and (not version_label or work_id not in old_title_work[title]):
            raise ValueError('Exact title collision requires a labelled edition sharing the existing workId: ' + entry[2]['title'])
        if title in new_titles:
            prior_work, prior_label = new_titles[title]
            if not version_label or not prior_label or prior_work != work_id:
                raise ValueError('Exact new title collision requires distinct labelled editions of one work: ' + entry[2]['title'])
        new_titles[title] = (work_id, version_label)
        new_editions.add(edition_id)
        new_source_hashes.add(source_hash)
    operations = []
    for target in targets:
        existing = {path.name.casefold() for path in target.iterdir()}
        added = [incoming.entries[id_][0] for id_ in new_ids]
        for rel in added:
            if rel.casefold() in existing:
                raise FileExistsError('New score path already exists (no automatic resume/overwrite): ' + str(target / rel))
        operations.append({'target': str(target), 'oldEntries': old_count,
                           'newEntries': final_count, 'newEntriesThisBatch': expected_new, 'addFiles': sorted(added)})
    return incoming, old_catalogs, new_ids, operations
'''
s=s[:start]+new_func+s[end:]
s=s.replace("'derivedFrom': 'validated staged 332-entry catalogue'", "'derivedFrom': 'validated staged additive catalogue'")
s=s.replace("'newBuiltinCount': len(plan['incoming'].entries)", "'newBuiltinCount': len(plan['newIds'])")
s=s.replace('addedScoresPerTarget=NEW_COUNT', "addedScoresPerTarget=len(plan['newIds'])")
s=s.replace("item['catalogState'] == 'original-132'", "item['catalogState'] == 'original-baseline'")
s=s.replace("('original-132' if current == original_hash else", "('original-baseline' if current == original_hash else")
s=s.replace("print(result['status'] + ': 132 -> 332; exactly 200 new POP909 scores per target; ' + args.runtime)", "print(result['status'] + ': additive batch applied/preflight; ' + str(result.get('newBuiltinCount', '?')) + ' new POP909 scores; ' + args.runtime)")
path.write_text(s,encoding='utf8')
print('patched generic updater')
