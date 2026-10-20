"""Explicit maintenance correction of owner-confirmed misattributed dialogue.

Not a model tool. The caller backs up the database, stops competing writers,
opens BEGIN IMMEDIATE, and supplies exact source fingerprints authorized by the
owner. Retractions remove dependent context without resetting identity/IDs.
"""
import hashlib
import json
import time


def correct_sources(db, targets, validate=None):
    selected=[]
    for target in targets:
        row=db.execute('SELECT rowid,op_id,role,content FROM archive WHERE rowid=?',(target['seq'],)).fetchone()
        if not row:continue
        if row['role']!=target['role'] or hashlib.sha256(row['content'].encode()).hexdigest()!=target['sha256']:
            raise ValueError('source fingerprint mismatch; no correction applied')
        selected.append((row,target))
    if not selected:return {'retracted':0,'removed_memory_entries':0}
    device=db.execute('SELECT memory,identity FROM device WHERE singleton=1').fetchone()
    memory=json.loads(device['memory']);source_ids=set()
    hashes={target['sha256'] for _,target in selected}
    for key in ('history','pending'):
        source_ids.update(item['id'] for item in memory.get(key,[]) if hashlib.sha256(item.get('content','').encode()).hexdigest() in hashes)
    for row,_ in selected:
        op=db.execute('SELECT result FROM operations WHERE op_id=?',(row['op_id'],)).fetchone()
        if op and type(op[0]) is int and op[0]>0:source_ids.add(op[0])
    removed=0
    for key in ('history','pending','cards','growth','changes'):
        before=memory.get(key,[])
        memory[key]=[item for item in before if not ((key in ('history','pending') and item.get('id') in source_ids) or item.get('source_id') in source_ids or any(x in source_ids for x in item.get('evidence',[])))]
        removed+=len(before)-len(memory[key])
    memory['summary']=''
    if validate:validate(memory)
    db.execute('CREATE TABLE IF NOT EXISTS source_retractions(source TEXT PRIMARY KEY,content_sha256 TEXT NOT NULL,reason TEXT NOT NULL,created INTEGER NOT NULL)')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    traces=set()
    if 'companion_turns' in tables:
        for row in db.execute('SELECT id,candidate_hash,source_id FROM companion_turns'):
            if row['candidate_hash'] in hashes or row['source_id'] in source_ids:traces.add(row['id'])
        db.executemany('DELETE FROM companion_turns WHERE id=?',((trace,) for trace in traces))
    if 'companion_threads' in tables:
        db.executemany('DELETE FROM companion_threads WHERE source_id=?',((n,) for n in source_ids))
    if 'companion_checks' in tables:
        db.executemany('DELETE FROM companion_checks WHERE source_id=?',((n,) for n in source_ids))
    if 'companion_events' in tables:
        for row in db.execute('SELECT id,detail FROM companion_events').fetchall():
            detail=json.loads(row['detail'])
            if detail.get('trace') in traces or detail.get('source_id') in source_ids:
                db.execute('DELETE FROM companion_events WHERE id=?',(row['id'],))
    for row,target in selected:
        db.execute('DELETE FROM archive WHERE op_id=?',(row['op_id'],))
        for table in ('recall_terms','recall_indexed'):
            if table in tables:db.execute('DELETE FROM '+table+' WHERE source=?',(row['op_id'],))
        db.execute('INSERT OR IGNORE INTO source_retractions VALUES(?,?,?,?)',(row['op_id'],target['sha256'],target['reason'],int(time.time())))
    db.execute('UPDATE device SET memory=?,revision=revision+1 WHERE singleton=1',(json.dumps(memory,ensure_ascii=False,separators=(',',':')),))
    return {'retracted':len(selected),'removed_memory_entries':removed}
