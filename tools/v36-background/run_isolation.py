from pathlib import Path
from adb_client import shell, push, devices
import argparse, hashlib, json, time, datetime, shlex
p=argparse.ArgumentParser()
p.add_argument('--serial',required=True);p.add_argument('--package',required=True,choices=['org.esurfing.hunan.isolation'])
p.add_argument('--apk',required=True);p.add_argument('--label',required=True)
p.add_argument('--probes',nargs='+',default=['AlarmProbe','DiagnosticsProbe','SessionProbe','CompatProbe'])
p.add_argument('--install',action='store_true');a=p.parse_args()
assert all(x in ['AlarmProbe','DiagnosticsProbe','SessionProbe','CompatProbe','StabilityProbe','RepairMenuProbe'] for x in a.probes)
assert a.label.replace('-','').isalnum()
apk=Path(a.apk).resolve(strict=True);package=a.package
report={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'package':package,'apkSha256':hashlib.sha256(apk.read_bytes()).hexdigest().upper(),'results':[]}
dest=Path(__file__).parent/'evidence'/f'{a.label}.json';assert not dest.exists()
def run(command,timeout=30):
    code,out,err=shell(a.serial,command,timeout)
    return code,out.decode(errors='replace').strip()
try:
    assert any(x.split()[:2]==[a.serial,'device'] for x in devices().splitlines())
    report['api']=run('getprop ro.build.version.sdk')[1]
    report['model']=run('getprop ro.product.model')[1]
    if a.install:
        remote='/data/local/tmp/campus-s1-background-isolation.apk'
        push(a.serial,apk,remote)
        code,out=run('pm install -r '+remote,120)
        report['install']={'exitCode':code,'result':out};assert code==0 and out=='Success'
        assert run('rm -f '+remote)[0]==0
    path=run('pm path '+package)[1].removeprefix('package:')
    assert run('sha256sum '+shlex.quote(path))[1].split()[0].upper()==report['apkSha256']
    for probe in a.probes:
        started=time.monotonic()
        code,out=run(f'am instrument -w {package}/org.esurfing.hunan.{probe}',300)
        values=[line.removeprefix('INSTRUMENTATION_RESULT: result=') for line in out.splitlines() if line.startswith('INSTRUMENTATION_RESULT: result=')]
        value=values[-1] if values else ''
        passed=(json.loads(value).get('status')=='PASS') if value.startswith('{') else value.startswith('PASS')
        status='PASS' if code==0 and 'INSTRUMENTATION_CODE: -1' in out and passed else 'FAIL'
        result={'probe':probe,'status':status,'exitCode':code,'durationSeconds':round(time.monotonic()-started,2),'output':out}
        report['results'].append(result)
        dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if status!='PASS':break
finally:
    report['cleanup']={'forceStopExit':run('am force-stop '+package)[0]}
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
