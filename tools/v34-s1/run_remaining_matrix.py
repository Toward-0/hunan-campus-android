"""Run approved APIs serially on one explicit, current-revision emulator port."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
import argparse, datetime, hashlib, json, os, re, subprocess, sys

APIS=(26,29,31,33,36)
STATUSES={'PASS','FAIL','NOT_RUN','BLOCKED'}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest().upper()
def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def ensure(value,message):
    if not value:raise ValueError(message)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('serial','package','apk','sha256','source-id','iteration','initial-boot','initial-boot-sha256'):
        p.add_argument('--'+k,required=True)
    p.add_argument('--version',type=int,required=True)
    a=p.parse_args();r=require_mutable_stage()
    ensure(a.serial=='emulator-5556' and a.package=='org.esurfing.hunan.isolation','Reviewed emulator port and isolated package required')
    ensure(re.fullmatch(r'r[1-9][0-9]*',a.iteration),'Explicit build iteration required')
    ensure(re.fullmatch(r'[A-Fa-f0-9]{64}',a.sha256) and re.fullmatch(r'[A-Fa-f0-9]{64}',a.source_id),'Explicit digest bindings required')
    apk=Path(a.apk).resolve(strict=True)
    ensure(apk.is_relative_to(r) or apk.is_relative_to(r.parent.parent/'outputs'/r.name),'APK outside current revision')
    ensure(sha(apk)==a.sha256.upper(),'APK changed')
    ensure(sha(r/'evidence'/('build-input-'+a.iteration+'.json'))==a.source_id.upper(),'Source manifest changed')
    boot=Path(a.initial_boot).resolve(strict=True)
    ensure(boot.is_relative_to(r/'evidence') and sha(boot)==a.initial_boot_sha256.upper(),'Initial AVD record changed')
    initial=load(boot)
    ensure(initial.get('status')=='PASS' and initial.get('api')==26 and initial.get('deviceAlias')==a.serial,'Initial record does not bind API26 emulator')
    path=assert_stage_write(r/'evidence'/(a.iteration+'-remaining-matrix-sequence.json'))
    ensure(not path.exists(),'Preserve earlier matrix sequence')
    report={'testId':'REMAINING-API-MATRIX','sourceId':a.source_id.upper(),'apkSha256':a.sha256.upper(),
            'package':a.package,'versionCode':a.version,'startedAt':now(),'status':'NOT_RUN',
            'cases':[{'api':api,'required':api!=36,'status':'NOT_RUN','reason':'Not executed'} for api in APIS],
            'scope':'Automation only; every UI combination also needs explicit screenshot review',
            'mainApplicationActions':0,'historicalAvdDeletes':0}
    def persist():
        temporary=assert_stage_write(path.with_suffix('.json.tmp'))
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,path)
    def markers():return [name for name in ('STOP_UI_MATRIX','STOP_DEVICE_MATRIX') if (r/name).exists()]
    def require_unpaused():
        found=markers()
        if found:
            report['pausedBy']=found
            raise ValueError('Revision pause marker; leave current emulator for reviewed recovery')
    def run(script,args,timeout):
        return subprocess.run([sys.executable,'-B',str(r/script),*args],timeout=timeout).returncode
    def verify_live_avd(boot_path,api):
        # Exact AVD verification precedes any installation, including initial
        # adoption. The following are fixed property reads only.
        from adb_client import devices,shell
        record=load(boot_path)
        ensure(record.get('status')=='PASS' and record.get('api')==api and record.get('deviceAlias')==a.serial,'Boot evidence mismatch')
        avd=Path(record.get('avd','')).resolve()
        ensure(avd.is_relative_to(r/'avd') and avd.name==f's1-json-ui-api{api}.avd','Boot AVD is outside this revision')
        online=[line.split() for line in devices().splitlines() if line.strip() and line.split()[0]==a.serial]
        ensure(len(online)==1 and online[0][1]=='device','Reviewed emulator is not online')
        values={}
        for key,prop in [('api','ro.build.version.sdk'),('qemu','ro.kernel.qemu'),
                         ('bootAvd','ro.boot.qemu.avd_name'),('kernelAvd','ro.kernel.qemu.avd_name')]:
            code,data,_=shell(a.serial,'getprop '+prop,10);ensure(code==0,'Live AVD query failed')
            values[key]=data.decode().strip()
        names={values['bootAvd'],values['kernelAvd']}-{''}
        ensure(values['api']==str(api) and values['qemu']=='1' and names=={avd.stem},'Live emulator is not the reviewed current-revision AVD')
        return {'api':api,'qemu':True,'avdName':avd.stem,'status':'PASS'}
    common=['--serial',a.serial,'--package',a.package,'--apk',str(apk),'--sha256',a.sha256.upper(),'--source-id',a.source_id.upper()]
    persist()
    try:
        # Fail before any device mutation if a sequence would accidentally reuse
        # a prior suite result rather than execute its reviewed unique labels.
        for api in APIS:
            prefix=a.iteration+'-api'+str(api)
            ensure(not (r/'evidence'/(prefix+'-matrix-suite.json')).exists(),'A suite summary already exists; do not reuse it implicitly')
            ensure(not (r/'evidence'/(prefix+'-avd-stop')).exists(),'A shutdown evidence label already exists')
        for row in report['cases']:
            api=row['api'];require_unpaused()
            row['startedAt']=now();row['reason']='Execution started';persist()
            if api!=26:
                label=a.iteration+'-matrix-01'
                code=run('start_emulator.py',['--api',str(api),'--port','5556','--label',label],420)
                row['bootExit']=code
                boot=r/'evidence'/f'emulator-api{api}-boot-{label}.json'
                ensure(code==0 and boot.exists() and load(boot).get('status')=='PASS','AVD did not start cleanly; stop sequence')
            row['bootRecord']=boot.relative_to(r).as_posix();row['bootRecordSha256']=sha(boot)
            row['liveAvdVerification']=verify_live_avd(boot,api)
            require_unpaused()
            prefix=a.iteration+'-api'+str(api)
            # This exceeds the SUM of all current child budgets plus setup:
            # four device probes + 2/4 UI cases, each with wrapper cleanup time.
            # A shorter outer timeout could kill the suite while leaving a UI
            # child restoring device settings.
            suite_timeout=180+(240+240)+(360+240)+(240+240)+(900+240)+(2 if api==26 else 4)*(600+240)
            row['suiteTimeoutSeconds']=suite_timeout
            row['suiteExit']=run('matrix-suite.py',common+['--api',str(api),'--version-code',str(a.version),'--labelprefix',prefix],suite_timeout)
            suite=r/'evidence'/(prefix+'-matrix-suite.json')
            ensure(suite.exists(),'No suite evidence; cleanup cannot be established')
            result=load(suite)
            ensure(result.get('sourceId')==a.source_id.upper() and result.get('apkSha256')==a.sha256.upper()
                   and result.get('package')==a.package and result.get('api')==api and result.get('versionCode')==a.version,
                   'Suite evidence identity does not match this run')
            ensure(result.get('status') in STATUSES,'Unknown suite result status')
            expected_exit=0 if result['status']=='PASS' else 2 if result['status']=='BLOCKED' else 1
            ensure(row['suiteExit']==expected_exit,'Suite exit code disagrees with evidence')
            row.update(status=result['status'],reason='Actual current-APK suite result',evidence=suite.relative_to(r).as_posix(),evidenceSha256=sha(suite))
            persist()
            ensure(not result.get('stopReason'),'Suite stopped early; keep emulator for reviewed recovery')
            require_unpaused()
            recovery_label=prefix+'-avd-stop'
            code=run('restore_revision.py',common+['--label',recovery_label,'--version',str(a.version),'--expected-api',str(api),
                     '--mode','emulator','--record',str(boot),'--record-sha256',sha(boot)],240)
            recovery=r/'evidence'/recovery_label/'result.json'
            ensure(recovery.exists(),'No shutdown evidence')
            restored=load(recovery)
            ensure(code==0 and restored.get('status')=='PASS' and restored.get('sourceId')==a.source_id.upper()
                   and restored.get('apkSha256')==a.sha256.upper() and restored.get('package')==a.package
                   and restored.get('api')==api and restored.get('deviceAlias')==a.serial
                   and restored.get('recoveryRecordSha256')==sha(boot)
                   and any(item.get('id')=='emulator-disconnected' and item.get('status')=='PASS' for item in restored.get('checks',[])),
                   'Verified current AVD shutdown failed; stop sequence')
            ensure(any(item.get('id')=='emulator-process-tree-exited' and item.get('status')=='PASS' for item in restored.get('checks',[])),
                   'Verified current AVD shutdown failed; stop sequence')
            row.update(shutdownEvidence=recovery.relative_to(r).as_posix(),shutdownEvidenceSha256=sha(recovery),
                       shutdownStatus='PASS',finishedAt=now());persist()
        values=[x['status'] for x in report['cases']]
        report['status']='FAIL' if 'FAIL' in values else 'BLOCKED' if any(x!='PASS' for x in values) else 'PASS'
    except Exception as error:
        report.update(status='FAIL' if any(x['status']=='FAIL' for x in report['cases']) else 'BLOCKED',exceptionType=type(error).__name__)
        report['stopReason']=str(error) if isinstance(error,ValueError) else type(error).__name__
        for row in report['cases']:
            if row['status']=='NOT_RUN':row['reason']='Sequence stopped before a reliable case result: '+report['stopReason']
    finally:
        report['finishedAt']=now();persist()
        print(json.dumps({'sequence':path.name,'status':report['status'],'completedApis':[x['api'] for x in report['cases'] if x.get('shutdownStatus')=='PASS'],'stopReason':report.get('stopReason')},ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
