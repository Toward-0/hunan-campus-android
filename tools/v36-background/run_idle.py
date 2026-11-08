from pathlib import Path
from adb_client import shell,devices
import argparse, concurrent.futures, json, hashlib, shlex, time, datetime
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--package',required=True,choices=['org.esurfing.hunan.isolation']);p.add_argument('--apk',required=True);p.add_argument('--label',required=True);a=p.parse_args()
assert a.label.replace('-','').isalnum()
package=a.package;apk=Path(a.apk).resolve(strict=True)
report={'testId':'FORCED-IDLE-SCHEDULER','time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'apkSha256':hashlib.sha256(apk.read_bytes()).hexdigest().upper(),'package':package,'commands':[],'status':'FAIL'}
dest=Path(__file__).parent/'evidence'/f'{a.label}.json';assert not dest.exists()
def run(name,cmd,timeout=20):
    code,data,err=shell(a.serial,cmd,timeout);out=data.decode(errors='replace').strip()
    report['commands'].append({'id':name,'exitCode':code})
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    # This platform's whitelist ShellCommand returns -1 (255) even after
    # printing Added/Removed. Accept only the exact success response and then
    # independently confirm the actual whitelist state. All other commands
    # retain the zero-exit requirement; permission failures never qualify.
    if name in ['exempt-isolation','restore-exemption'] and code==255:
        expected=('Added: ' if name=='exempt-isolation' else 'Removed: ')+package
        assert out==expected and not err,name
        verify_code,verify,_=shell(a.serial,'cmd deviceidle whitelist ='+package,20)
        assert verify_code==0 and verify.decode().strip()==('true' if name=='exempt-isolation' else 'false'),name
    else:assert code==0,name
    return out
changed=False;original_white=None;screen=None
try:
    assert any(x.split()[:2]==[a.serial,'device'] for x in devices().splitlines())
    path=run('package-path','pm path '+package).removeprefix('package:')
    assert run('apk-hash','sha256sum '+shlex.quote(path)).split()[0].upper()==report['apkSha256']
    report['api']=run('api','getprop ro.build.version.sdk');report['model']=run('model','getprop ro.product.model')
    assert run('initial-idle','cmd deviceidle get deep') in ['ACTIVE','INACTIVE']
    assert run('not-forced',"dumpsys deviceidle | awk '/mForceIdle=/ {for(i=1;i<=NF;i++)if($i~/^mForceIdle=/)print $i}'")=='mForceIdle=false'
    screen=run('initial-screen',"dumpsys power | awk '/mWakefulness=/ {print $1; exit}'")
    original_white=run('initial-exemption','cmd deviceidle whitelist ='+package)
    assert original_white in ['true','false']
    changed=True
    if original_white=='false':run('exempt-isolation','cmd deviceidle whitelist +'+package)
    run('wake-for-setup','input keyevent 224')
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        pending=pool.submit(run,'instrument',f'am instrument -w {package}/org.esurfing.hunan.IdleSchedulerProbe',300)
        try:
            # Keep the CPU awake only during the probe's setup. In particular,
            # a locked realme can turn its screen off before the setup sleep
            # finishes. No host queries occur during the measured idle window.
            for _ in range(6):
                time.sleep(3)
                run('wake-during-setup','input keyevent 224')
            ready=r'''tail -n 1 no_backup/timing-v2/trace.jsonl | awk '/"point":"SCHEDULER"/ && /"kind":"HEARTBEAT"/ {print "armed"}' '''
            assert run('verify-first-alarm-armed','run-as '+package+' sh -c '+shlex.quote(ready))=='armed'
            run('screen-off','input keyevent 223')
            report['forcedIdle']=run('force-idle','cmd deviceidle force-idle')
            assert run('actual-idle','cmd deviceidle get deep')=='IDLE'
            out=pending.result(timeout=280)
            report['output']=out
            value=[line.removeprefix('INSTRUMENTATION_RESULT: result=') for line in out.splitlines() if line.startswith('INSTRUMENTATION_RESULT: result=')][-1]
            result=json.loads(value);report['result']=result
            assert result['status']=='PASS' and result['callbacksAfter']==0
            assert len(result['samples'])==3
            assert all(s['idle'] and not s['interactive'] and s['delayMs']<=3000 for s in result['samples'])
            report['status']='PASS'
        finally:
            run('unforce-idle','cmd deviceidle unforce')
            run('stop-isolation','am force-stop '+package)
except Exception as e:report['errorType']=type(e).__name__
finally:
    if changed:
        for name,cmd in [('unforce-final','cmd deviceidle unforce'),('stop-final','am force-stop '+package),
                         ('restore-exemption','cmd deviceidle whitelist -'+package) if original_white=='false' else ('verify-no-change','cmd deviceidle whitelist ='+package),
                         ('restore-screen','input keyevent 224') if screen=='mWakefulness=Awake' else ('verify-screen','cmd deviceidle get screen')]:
            try:run(name,cmd)
            except Exception:report.setdefault('cleanupFailures',[]).append(name)
        try:
            report['restoredExemption']=run('verify-exemption','cmd deviceidle whitelist ='+package)==original_white
            report['restoredIdle']=run('verify-unforced','cmd deviceidle get force')=='false'
            if not report['restoredExemption'] or not report['restoredIdle']:report['status']='FAIL'
        except Exception:report['status']='FAIL'
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False),flush=True)
