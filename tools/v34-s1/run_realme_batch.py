"""Sequential realme isolation batches. Explicit APKs/device; no main-app access."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import devices,shell
import argparse,datetime,hashlib,json,os,re,subprocess,sys,time

def main():
    r=require_mutable_stage()
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('serial','source-id','revision-label','phone-apk','phone-sha256','arm32-apk','arm32-sha256'):p.add_argument('--'+key,required=True)
    p.add_argument('--version',type=int,required=True)
    p.add_argument('--phase',required=True,choices=['native64','stability64','ui64','native32','restore-phone'])
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9-]+',a.revision_label):raise ValueError('Invalid revision label')
    if not re.fullmatch(r'[A-Za-z0-9._-]+',a.source_id):raise ValueError('Invalid source ID')
    online=[line.split() for line in devices().splitlines() if line.strip() and line.split()[0]==a.serial]
    if len(online)!=1 or online[0][1]!='device':raise RuntimeError('Explicit realme is not online')
    def value(command):
        code,data,_=shell(a.serial,command,10)
        if code!=0:raise RuntimeError('Identity query failed')
        return data.decode().strip()
    if value('getprop ro.product.model')!='RMX3820' or value('getprop ro.build.version.sdk')!='34' or value('getconf PAGE_SIZE')!='4096' or value('getprop ro.kernel.qemu')=='1':
        raise RuntimeError('Current device differs from approved realme environment')
    abis=value('getprop ro.product.cpu.abilist').split(',')
    if not {'arm64-v8a','armeabi-v7a'}.issubset(abis):raise RuntimeError('Required ARM process ABIs unavailable')
    for path,digest in ((a.phone_apk,a.phone_sha256),(a.arm32_apk,a.arm32_sha256)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()!=digest.upper():raise RuntimeError('Explicit APK hash differs')
    summary={'testId':'REALME-BATCH-'+a.phase,'sourceId':a.source_id,'deviceAlias':'RMX3820','api':34,'pageSize':4096,
             'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':[]}
    summary_path=assert_stage_write(r/'evidence'/(a.revision_label+'-realme34-batch-'+a.phase+'.json'))
    if summary_path.exists():raise RuntimeError('Keep earlier batch evidence')
    def persist():summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    def call(label,arguments,timeout):
        print(json.dumps({'batch':a.phase,'starting':label}),flush=True)
        completed=subprocess.run([sys.executable,'-B',*arguments],timeout=timeout)
        result_path=r/'evidence'/label/'result.json'
        data=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {'status':'FAIL','reason':'result missing'}
        summary['results'].append({'label':label,'status':data.get('status','FAIL'),'processExit':completed.returncode,'evidence':result_path.relative_to(r).as_posix()})
        persist()
        print(json.dumps({'completed':label,'status':data.get('status'),'reason':data.get('reason')},ensure_ascii=False),flush=True)
        return data
    def probe(suffix,name,mode=None,install=False,bits=None,timeout=240,arm32=False):
        label=a.revision_label+'-realme34-'+suffix
        apk,digest=(a.arm32_apk,a.arm32_sha256) if arm32 else (a.phone_apk,a.phone_sha256)
        command=[str(r/'run_device.py'),'--serial',a.serial,'--package','org.esurfing.hunan.isolation',
                 '--apk',apk,'--sha256',digest,'--source-id',a.source_id,'--version',str(a.version),
                 '--label',label,'--probe',name,'--timeout',str(timeout)]
        if install:command+=['--install']
        if mode:command+=['--mode',mode]
        if bits:command+=['--process-bits',str(bits)]
        data=call(label,command,timeout+240 if install else timeout+120)
        if install and not data.get('installSuccess'):
            raise RuntimeError('Installation was not confirmed; stop and ask user about installer, without retry')
        if type(data.get('cleanupExit')) is not int or data['cleanupExit']!=0:
            if summary['results'][-1]['status']=='PASS':
                summary['results'][-1]['status']='FAIL'
                summary['results'][-1]['reason']='Explicit successful isolation cleanup is missing'
                persist()
            raise RuntimeError('Isolation cleanup missing or failed; stop batch')
        return data
    try:
        if a.phase=='native64':
            probe('jni64','CompatProbe',install=True,bits=64)
            probe('menu64','RepairMenuProbe')
            probe('diagnostics-export64','DiagnosticsProbe',mode='export',timeout=360)
            probe('diagnostics-session64','DiagnosticsProbe',mode='session',timeout=360)
        elif a.phase=='stability64':
            for mode in ('account','lifecycle','repair'):probe('stability-'+mode+'64','StabilityProbe',mode=mode,timeout=900)
        elif a.phase=='native32':
            probe('jni32','CompatProbe',install=True,bits=32,arm32=True)
            probe('menu32','RepairMenuProbe',arm32=True)
            probe('diagnostics-export32','DiagnosticsProbe',mode='export',timeout=360,arm32=True)
        elif a.phase=='restore-phone':
            probe('restore-phone','install-only',install=True)
        elif a.phase=='ui64':
            need_current=False
            def ui(font,nav):
                label=a.revision_label+'-realme34-ui-font'+font[0]+'-'+nav
                command=[str(r/'run_ui.py'),'--serial',a.serial,'--package','org.esurfing.hunan.isolation',
                    '--apk',a.phone_apk,'--sha256',a.phone_sha256,'--source-id',a.source_id,
                    '--version-code',str(a.version),'--api','34','--abi','arm64-v8a','--font',font,
                    '--nav',nav,'--cutout','current','--label',label]
                data=call(label,command,480)
                if data.get('cleanupFailure') or any(x.get('status')=='FAIL' for x in data.get('restoration',[])):
                    raise RuntimeError('UI settings restoration failed; stop further UI')
                return data
            for nav in ('gesture','three'):
                for font in ('1.0','2.0'):
                    if ui(font,nav).get('status')=='BLOCKED':need_current=True
            if need_current:
                for font in ('1.0','2.0'):ui(font,'current')
        summary['status']='PASS' if all(x['status']=='PASS' for x in summary['results']) else 'FAIL'
    except Exception as error:
        summary.update(status='BLOCKED' if isinstance(error,RuntimeError) else 'FAIL',reason=str(error) if isinstance(error,RuntimeError) else type(error).__name__)
        raise
    finally:
        summary['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat();persist()
    return 0 if summary['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
