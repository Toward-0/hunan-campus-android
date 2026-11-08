"""Sequential isolated emulator matrix; no authentication, AVD lifecycle, or main-app actions."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import query_page_size, PageSizeUnavailable
import argparse, datetime, hashlib, json, os, re, subprocess, sys, time

PACKAGE='org.esurfing.hunan.isolation'
STATUSES={'PASS','FAIL','NOT_RUN','BLOCKED'}
MARKERS=('STOP_UI_MATRIX','STOP_DEVICE_MATRIX')
def timestamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def ensure(condition,message):
    if not condition:raise ValueError(message)

def plan_cases(api,full_safety):
    cases=[{'suffix':'install-jni','kind':'device','probe':'CompatProbe','timeout':240,'install':True,'bits':64}]
    # Validate the changed UI first, including large text, before longer probes.
    # API35's eight combinations have separate root-owned evidence.
    navigation=['current'] if api==26 else [] if api==35 else ['gesture','three']
    cases += [{'suffix':'ui-font'+font[0]+'-'+nav+'-none','kind':'ui','font':font,
               'navigation':nav,'cutout':'none','timeout':600}
              for font in ('2.0','1.0') for nav in navigation]
    cases += [
        {'suffix':'diagnostics-export','kind':'device','probe':'DiagnosticsProbe','mode':'export','timeout':360},
        {'suffix':'repair-menu','kind':'device','probe':'RepairMenuProbe','timeout':240},
        {'suffix':'stability-account','kind':'device','probe':'StabilityProbe','mode':'account','timeout':900},
    ]
    if full_safety:
        cases += [{'suffix':'stability-'+mode,'kind':'device','probe':'StabilityProbe','mode':mode,'timeout':900}
                  for mode in ('repair','lifecycle')]
    return cases

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('serial','package','apk','sha256','source-id','labelprefix'):p.add_argument('--'+key,required=True)
    p.add_argument('--api',required=True,type=int,choices=[26,29,31,33,35,36])
    p.add_argument('--version-code',type=int,help='Optional explicit expected code; otherwise read reviewed build.gradle.kts')
    p.add_argument('--full-safety',action='store_true')
    a=p.parse_args()
    ensure(a.package==PACKAGE,'Only isolated package is permitted')
    ensure(re.fullmatch(r'emulator-[0-9]+',a.serial),'This suite is emulator-only; use an explicit emulator serial')
    ensure(re.fullmatch(r'[A-Za-z0-9-]+',a.labelprefix),'Invalid label prefix')
    ensure(re.fullmatch(r'[A-Za-z0-9._-]+',a.source_id),'Invalid source identifier')
    ensure(re.fullmatch(r'[a-fA-F0-9]{64}',a.sha256),'Invalid APK SHA256')
    r=require_mutable_stage()
    summary_path=assert_stage_write(r/'evidence'/(a.labelprefix+'-matrix-suite.json'))
    ensure(not summary_path.exists(),'Preserve earlier suite evidence; use a new label prefix')
    gradle=(r/'source/app/build.gradle.kts').read_text(encoding='utf-8')
    version=int(re.search(r'versionCode\s*=\s*(\d+)',gradle).group(1))
    ensure(version>33 and (a.version_code is None or a.version_code==version),'Version differs from current reviewed source')
    cases=plan_cases(a.api,a.full_safety)
    rows=[]
    for case in cases:
        label=a.labelprefix+'-'+case['suffix']
        ensure(not (r/'evidence'/label).exists(),'A case label already exists; do not overwrite/re-run implicitly')
        rows.append({'testId':case['suffix'],'label':label,'sourceId':a.source_id,'apkSha256':a.sha256.upper(),
            'package':PACKAGE,'expectedApi':a.api,'expectedAbi':'x86_64','versionCode':version,
            'status':'NOT_RUN','reason':'Not executed','evidence':'evidence/'+label+'/result.json'})
    report={'testId':'EMULATOR-MATRIX-SUITE','sourceId':a.source_id,'apkSha256':a.sha256.upper(),
        'package':PACKAGE,'api':a.api,'expectedAbi':'x86_64','deviceAlias':a.serial,'versionCode':version,
        'startedAt':timestamp(),'status':'NOT_RUN','fullSafetyRequested':a.full_safety,'cases':rows,
        'scope':'Current APK isolated emulator cases only; UI automation PASS still requires screenshot review.',
        'api35UiScope':'Eight API35 UI combinations are separately owned by the root task; not counted here.',
        'automaticMainAppActions':0,'avdStartStopActions':0,'newNetworkActions':0}
    def persist():
        temporary=assert_stage_write(summary_path.with_suffix('.json.tmp'))
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,summary_path)
    def pause_markers():return [name for name in MARKERS if (r/name).exists()]
    def stop_remaining(index,reason):
        report['stopReason']=reason
        for row in rows[index:]:
            if row['status']=='NOT_RUN':row['reason']=reason
    persist()
    try:
        markers=pause_markers()
        if markers:
            report.update(status='BLOCKED',pausedBy=markers)
            stop_remaining(0,'Current revision pause marker exists; no device actions performed')
            return 2
        apk=Path(a.apk).resolve(strict=True)
        ensure(apk.is_relative_to(r) or apk.is_relative_to(r.parent.parent/'outputs'/r.name),'APK outside current revision')
        ensure(hashlib.sha256(apk.read_bytes()).hexdigest().upper()==a.sha256.upper(),'Actual APK SHA256 differs')
        # Minimal existing smart-socket white-list reads bind the API before installation.
        # These do not start adb, an AVD, an app, or a network authentication request.
        from adb_client import devices,shell
        online=[line.split() for line in devices().splitlines() if line.strip() and line.split()[0]==a.serial]
        ensure(len(online)==1 and online[0][1]=='device','Explicit emulator is not online/authorized')
        properties={}
        for name,command in [('api','getprop ro.build.version.sdk'),('qemu','getprop ro.kernel.qemu'),
                             ('abis','getprop ro.product.cpu.abilist')]:
            code,data,_=shell(a.serial,command,10)
            ensure(code==0,'Emulator environment query failed')
            properties[name]=data.decode('utf-8',errors='strict').strip()
        ensure(int(properties['api'])==a.api and properties['qemu']=='1' and 'x86_64' in properties['abis'].split(','),
               'Actual emulator API/ABI/qemu differs from requested environment')
        page=query_page_size(a.serial)
        report['environment']={'api':a.api,'qemu':True,'abis':properties['abis'].split(','),'pageSize':page['pageSize'],'pageSizeEvidence':page}
        for index,(case,row) in enumerate(zip(cases,rows)):
            markers=pause_markers()
            if markers:
                report['pausedBy']=markers
                stop_remaining(index,'Current revision pause marker exists; not executed')
                break
            common=['--serial',a.serial,'--package',PACKAGE,'--apk',str(apk),'--sha256',a.sha256,
                    '--source-id',a.source_id,'--label',row['label']]
            if case['kind']=='device':
                arguments=[str(r/'run_device.py'),*common,'--version',str(version),'--probe',case['probe'],'--timeout',str(case['timeout'])]
                if case.get('install'):arguments+=['--install']
                if case.get('mode'):arguments+=['--mode',case['mode']]
                if case.get('bits'):arguments+=['--process-bits',str(case['bits'])]
            else:
                arguments=[str(r/'run_ui.py'),*common,'--version-code',str(version),'--api',str(a.api),
                           '--abi','x86_64','--font',case['font'],'--nav',case['navigation'],'--cutout',case['cutout']]
            row['startedAt']=timestamp()
            print(json.dumps({'starting':row['label'],'api':a.api}),flush=True)
            # Existing child scripts own probe timeouts and finally restoration.
            # Pause markers between cases do not kill a child while it is restoring settings.
            exit_code=None
            try:
                child=subprocess.run([sys.executable,'-B',*arguments],timeout=case['timeout']+240)
                exit_code=child.returncode
            except subprocess.TimeoutExpired:
                row['executionException']='TimeoutExpired'
            except OSError:
                row['executionException']='OSError'
            row['processExit']=exit_code
            result_path=r/row['evidence']
            data=None
            if result_path.is_file():
                try:data=json.loads(result_path.read_text(encoding='utf-8-sig'))
                except (ValueError,OSError):row['executionException']='InvalidResult'
            if data is None:
                row.update(status='NOT_RUN',reason='No valid result was generated; execution cannot be counted')
                stop_remaining(index+1,'Previous child has no reliable cleanup result; recovery review required')
                break
            row['resultSha256']=hashlib.sha256(result_path.read_bytes()).hexdigest().upper()
            bindings=(data.get('sourceId')==a.source_id and data.get('package')==PACKAGE
                      and data.get('apkSha256','').upper()==a.sha256.upper())
            try:api_matches=int(data.get('api',-1))==a.api
            except (ValueError,TypeError):api_matches=False
            status=data.get('status')
            if not bindings or status not in STATUSES:
                row.update(status='FAIL',reason='Result identity/status does not match this exact case')
            elif status=='PASS' and (not api_matches or data.get('versionCode')!=version or exit_code!=0):
                row.update(status='FAIL',reason='PASS rejected: actual environment/version/process exit mismatched')
            else:
                row['status']=status
                row['reason']=data.get('reason','Actual child result')
            row['finishedAt']=timestamp()
            persist()
            print(json.dumps({'completed':row['label'],'status':row['status']},ensure_ascii=False),flush=True)
            if case.get('install') and (not data.get('installSuccess') or data.get('installedApkSha256')!=a.sha256.upper()):
                stop_remaining(index+1,'Installation/hash was not confirmed; no retry or dependent testing')
                break
            if case['kind']=='device' and (type(data.get('cleanupExit')) is not int or data['cleanupExit']!=0):
                if row['status']=='PASS':
                    row['status']='FAIL';row['reason']='PASS rejected: explicit successful isolated cleanup is missing'
                stop_remaining(index+1,'Isolated fixture cleanup is missing or failed; recovery review required')
                break
            if case['kind']=='ui':
                restoration=data.get('restoration',[])
                failed=(data.get('cleanupFailure') or any(item.get('status')=='FAIL' for item in restoration))
                if failed:
                    row['status']='FAIL';row['reason']='UI cleanup/restoration failed'
                    stop_remaining(index+1,'UI restoration failed; no further UI case is safe')
                    break
                if row['status']=='PASS':
                    if not restoration or not all(item.get('status')=='PASS' for item in restoration):
                        row['status']='FAIL';row['reason']='Successful UI case lacks verified restoration'
                        stop_remaining(index+1,'UI restoration cannot be verified; no further UI case is safe')
                        break
            # Assertion failure with successful cleanup does not suppress independent cases.
        if any(row['status']=='FAIL' for row in rows):report['status']='FAIL'
        elif any(row['status'] in ('BLOCKED','NOT_RUN') for row in rows):report['status']='BLOCKED'
        else:report['status']='PASS'
    except PageSizeUnavailable as error:
        report.update(status='BLOCKED',reason=str(error),pageSizeAttempts=error.attempts)
        stop_remaining(0,'Exact page size could not be verified; not executed')
    except Exception as error:
        report.update(status='FAIL',exceptionType=type(error).__name__)
        if isinstance(error,ValueError):report['reason']=str(error)
        stop_remaining(0,'Suite preflight or orchestration failed; not executed')
    finally:
        report['finishedAt']=timestamp();persist()
        print(json.dumps({'suite':summary_path.name,'status':report['status'],
                          'counts':{s:sum(row['status']==s for row in rows) for s in sorted(STATUSES)},
                          'stopReason':report.get('stopReason')},ensure_ascii=False),flush=True)
    return 0 if report['status']=='PASS' else 2 if report['status']=='BLOCKED' else 1

if __name__=='__main__':raise SystemExit(main())
