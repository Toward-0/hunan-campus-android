"""Re-hash the four sealed baseline roots; never modifies those roots."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
import argparse, datetime, hashlib, json, re, stat

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest().upper()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-id',required=True);p.add_argument('--label',required=True)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Fa-f0-9]{64}',a.source_id) or not re.fullmatch(r'r[0-9]+-protected(?:-final)?',a.label):
        raise ValueError('Explicit source hash and revision label required')
    r=require_mutable_stage()
    before=r/'evidence/protected-before.json'
    previous=json.loads(before.read_text(encoding='utf-8-sig'))
    old=Path('D:/codex/2026-11-06/d-codex-2026-11-05-jian-3')
    roots=[old/'work/repair-menu-20261107-01/source',old/'outputs/repair-menu-20261107-01',
           old/'work/github-user-release-20261107-01/repository',old/'outputs/github-user-release-20261107-01']
    expected={str(Path(x['path']).absolute()).lower():x['sha256'].upper() for x in previous}
    if len(previous)!=1442 or len(expected)!=1442:raise ValueError('Unexpected initial baseline snapshot')
    for key in expected:
        if not any(Path(key).is_relative_to(v.resolve()) for v in roots):raise ValueError('Baseline path outside approved sealed roots')
    after=assert_stage_write(r/'evidence'/(a.label+'-after.json'))
    result=assert_stage_write(r/'evidence'/(a.label+'.json'))
    if after.exists() or result.exists():raise ValueError('Preserve previous audit; use a fresh reviewed audit label')
    current=[]
    for root in roots:
        for file in sorted(root.rglob('*')):
            if file.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Reparse point found in protected inventory; stop for review')
            if file.is_file():current.append({'path':str(file.absolute()),'sha256':sha(file)})
    actual={x['path'].lower():x['sha256'] for x in current}
    missing=set(expected)-set(actual);added=set(actual)-set(expected)
    changed=[key for key in expected.keys() & actual.keys() if expected[key]!=actual[key]]
    after.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
    data={'kind':'protected-baseline','iteration':a.label.split('-')[0],'testId':a.label,
          'status':'PASS' if not(missing or added or changed) and len(current)==len(actual)==1442 else 'FAIL',
          'sourceId':a.source_id.upper(),'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'before':{'path':before.relative_to(r).as_posix(),'sha256':sha(before)},
          'after':{'path':after.relative_to(r).as_posix(),'sha256':sha(after)},
          'children':[],'fileCountBefore':len(previous),'fileCountAfter':len(current),
          'missingCount':len(missing),'addedCount':len(added),'changedCount':len(changed),
          'expected':'The same 1442 files in four sealed roots, with identical SHA256 and no added/deleted files',
          'actual':'All file hashes and the complete root inventory compared; private absolute paths remain local'}
    result.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:data[key] for key in ('testId','status','fileCountBefore','fileCountAfter','missingCount','addedCount','changedCount')}))
    return 0 if data['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
