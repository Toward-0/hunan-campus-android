"""Restore only revision-captured isolation settings, or stop its verified AVD."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import devices, shell, query_page_size, PageSizeUnavailable
from emulator_process_guard import snapshot_emulator_processes, wait_recorded_processes_exit, terminate_verified_processes
import argparse, datetime, hashlib, json, re, shlex, time, subprocess

PACKAGE='org.esurfing.hunan.isolation'
OVERLAY=re.compile(r'com\.android\.internal\.(?:systemui\.navbar|display\.cutout\.emulation)\.[A-Za-z0-9_.]+')
class Blocked(RuntimeError): pass
def ensure(value,message):
    if not value:raise ValueError(message)
def main():
    stage=require_mutable_stage()
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('serial','package','apk','sha256','source-id','label','record','record-sha256'):p.add_argument('--'+key,required=True)
    p.add_argument('--expected-api',type=int,required=True);p.add_argument('--version',type=int,required=True)
    p.add_argument('--mode',choices=['isolation','emulator'],required=True)
    a=p.parse_args()
    ensure(a.package==PACKAGE,'Recovery is limited to the isolated package')
    ensure(re.fullmatch(r'[A-Za-z0-9-]+',a.label),'Invalid label')
    ensure(re.fullmatch(r'[A-Za-z0-9._-]+',a.source_id),'Invalid source identifier')
    out=assert_stage_write(stage/'evidence'/a.label);ensure(not out.exists(),'Use a new recovery label');out.mkdir()
    row={'testId':'RESTORE-'+a.mode.upper(),'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'sourceId':a.source_id,'package':PACKAGE,'status':'FAIL','commands':[],'checks':[],
         'mainApplicationActions':0,'historicalAvdDeletes':0,'globalAdbServerActions':0}
    def run(key,command,timeout=15):
        code,data,_=shell(a.serial,command,timeout)
        row['commands'].append({'id':key,'exitCode':code})
        ensure(code==0,'Recovery command failed: '+key)
        return data.decode('utf-8',errors='strict').strip()
    def overlays():
        # API26 has no awk. Device shell builtins emit only the two reviewed
        # overlay namespaces; the same strict names are then parsed in Python.
        command="set -o pipefail; cmd overlay list --user current | while IFS= read -r line; do case \"$line\" in *com.android.internal.systemui.navbar.*|*com.android.internal.display.cutout.emulation.*) printf '%s\\n' \"$line\";; esac; done"
        text=run('read-whitelisted-overlays',command)
        result={}
        for line in text.splitlines():
            match=re.fullmatch(r'\s*\[([x ])\]\s+('+OVERLAY.pattern+r')\s*',line)
            ensure(match is not None,'Unexpected overlay entry')
            result[match[2]]=match[1]=='x'
        return result
    try:
        apk=Path(a.apk).resolve(strict=True)
        digest=hashlib.sha256(apk.read_bytes()).hexdigest().upper()
        ensure(digest==a.sha256.upper(),'Recovery APK hash mismatch');row['apkSha256']=digest
        metadata=subprocess.run([str(stage/'sdk/build-tools/35.0.0/aapt.exe'),'dump','badging',str(apk)],capture_output=True,timeout=20)
        row['localMetadataExit']=metadata.returncode
        ensure(metadata.returncode==0,'Recovery APK metadata tool failed')
        meta=metadata.stdout.decode(errors='replace')
        ensure(re.search(r"package: name='"+re.escape(PACKAGE)+r"' versionCode='"+str(a.version)+r"'",meta),'Recovery APK package/version mismatch')
        apk_abis=set(re.findall(r"'([^']+)'",next(v for v in meta.splitlines() if v.startswith('native-code:'))))
        record_path=Path(a.record).resolve(strict=True)
        ensure(record_path.is_relative_to(stage/'evidence'),'Recovery evidence must belong to current revision')
        ensure(hashlib.sha256(record_path.read_bytes()).hexdigest().upper()==a.record_sha256.upper(),'Recovery record hash mismatch')
        record=json.loads(record_path.read_text(encoding='utf-8-sig'))
        row['recoveryRecord']=record_path.relative_to(stage).as_posix()
        row['recoveryRecordSha256']=a.record_sha256.upper()
        online=[v.split() for v in devices().splitlines() if v.strip() and v.split()[0]==a.serial]
        if len(online)!=1 or online[0][1]!='device':raise Blocked('Explicit recovery device is offline or unauthorized')
        api=int(run('device-api','getprop ro.build.version.sdk'));model=run('device-model','getprop ro.product.model')
        qemu=run('qemu-flag','getprop ro.kernel.qemu')
        abis=run('device-abis','getprop ro.product.cpu.abilist').split(',')
        ensure(api==a.expected_api,'Recovery device API mismatch')
        ensure(bool(apk_abis.intersection(abis)),'Recovery APK is not compatible with current device ABI')
        ensure(model in ('RMX3820','V2307A') or qemu=='1','Device outside confirmed scope')
        row.update(api=api,deviceAlias=a.serial if qemu=='1' else model,model=model)
        if a.mode=='emulator':
            ensure(re.fullmatch(r'emulator-(5554|5556|5558|5560|5562|5564)',a.serial),'Explicit emulator serial required')
            ensure(qemu=='1','Physical-device shutdown is prohibited')
            ensure(record.get('status')=='PASS' and record.get('deviceAlias')==a.serial and record.get('api')==api,'Boot record does not bind this emulator')
            avd=Path(record['avd']).resolve()
            ensure(avd.is_relative_to(stage/'avd') and avd.name==f's1-json-ui-api{api}.avd','Boot record AVD outside current revision')
            names={run('boot-avd-name','getprop ro.boot.qemu.avd_name'),run('kernel-avd-name','getprop ro.kernel.qemu.avd_name')}
            names.discard('')
            if names!={avd.stem}:raise Blocked('Cannot establish that the live emulator is this revision AVD')
            row['avdName']=avd.stem
            tools=json.loads((stage/'tools.local.json').read_text(encoding='utf-8-sig'))
            process_tree=snapshot_emulator_processes(avd.stem,a.serial,tools['EmulatorExecutable'])
            if not process_tree:raise Blocked('Cannot bind the live AVD to an exact Windows process tree')
            row['processTreeBefore']=process_tree
            try:run('power-off-verified-emulator','reboot -p',10)
            except (EOFError,OSError,TimeoutError):row['powerOffConnectionClosed']=True
            end=time.monotonic()+30
            while time.monotonic()<end:
                if not any(v.split()[0]==a.serial for v in devices().splitlines() if v.strip()):
                    row['checks'].append({'id':'emulator-disconnected','status':'PASS'});break
                time.sleep(1)
            else:raise Blocked('Emulator remained connected; no global ADB stop or unrelated process kill attempted')
            tree_exit=wait_recorded_processes_exit(process_tree,15)
            if tree_exit['status']!='PASS':
                row['exactProcessTerminations']=terminate_verified_processes(process_tree)
                if any(x['status']!='PASS' for x in row['exactProcessTerminations']):raise Blocked('Recorded process identity or termination failed; no alternate process targeted')
                tree_exit=wait_recorded_processes_exit(process_tree,15)
            row['processTreeExit']=tree_exit
            if tree_exit['status']!='PASS':raise Blocked('ADB disconnected but the verified AVD process tree remains')
            row['checks'].append({'id':'emulator-process-tree-exited','status':'PASS'})
        else:
            ensure(record.get('schemaVersion')==1 and record.get('stageId')==stage.name,'Unsupported/foreign restore journal')
            ensure(record.get('package')==PACKAGE and record.get('apkSha256','').upper()==digest and record.get('versionCode')==a.version,'Journal APK binding mismatch')
            ensure(int(record.get('api',-1))==api and record.get('model')==model,'Journal device environment mismatch')
            page_evidence=query_page_size(a.serial);page=page_evidence['pageSize'];row['pageSizeEvidence']=page_evidence
            ensure(record.get('pageSize')==page,'Journal page-size mismatch')
            package_path=run('installed-isolation-path','pm path '+PACKAGE)
            ensure(re.fullmatch(r'package:/data/app/[A-Za-z0-9_./~=+-]+\.apk',package_path),'Expected one isolated base APK')
            actual=run('installed-isolation-hash','sha256sum '+shlex.quote(package_path[8:])).split()[0].upper()
            ensure(actual==digest,'Installed isolated APK differs from journal')
            original=record.get('original',{});ensure(isinstance(original,dict) and original,'Missing restore values')
            run('stop-isolated-fixture','am force-stop '+PACKAGE)
            for key,namespace in [('font_scale','system'),('show_ime_with_hard_keyboard','secure')]:
                if key not in original or original[key] is None:continue
                value=original[key]
                ensure(isinstance(value,str) and re.fullmatch(r'null|[0-9.]+',value),'Invalid saved setting')
                current=run('read-'+key,'settings get '+namespace+' '+key)
                if current!=value:
                    command='settings delete '+namespace+' '+key if value=='null' else 'settings put '+namespace+' '+key+' '+value
                    run('restore-'+key,command)
                ensure(run('verify-'+key,'settings get '+namespace+' '+key)==value,'Restored setting differs from original')
                row['checks'].append({'id':key,'status':'PASS'})
            saved=original.get('overlays')
            if saved is not None:
                ensure(isinstance(saved,dict) and all(OVERLAY.fullmatch(k) and isinstance(v,bool) for k,v in saved.items()),'Invalid saved overlay state')
                current=overlays()
                ensure(set(current)==set(saved),'Available overlays changed; do not guess recovery')
                for enabled in (False,True):
                    for name,wanted in saved.items():
                        if wanted==enabled and current[name]!=wanted:
                            run('restore-overlay','cmd overlay '+('enable' if wanted else 'disable')+' --user current '+name)
                ensure(overlays()==saved,'Restored overlays differ from original')
                row['checks'].append({'id':'overlays','status':'PASS'})
            granted=original.get('notificationGranted')
            if granted is not None:
                ensure(api>=33 and isinstance(granted,bool),'Invalid saved notification state')
                command='set -o pipefail; dumpsys package '+PACKAGE+r' | while IFS= read -r line; do case "$line" in *android.permission.POST_NOTIFICATIONS:\ granted=true*) echo true;; *android.permission.POST_NOTIFICATIONS:\ granted=false*) echo false;; esac; done'
                before=run('notification-current',command)
                ensure(before in ('true','false'),'Cannot read isolated notification permission')
                if (before=='true')!=granted:run('restore-notification','pm '+('grant' if granted else 'revoke')+' '+PACKAGE+' android.permission.POST_NOTIFICATIONS')
                ensure((run('verify-notification',command)=='true')==granted,'Notification restoration mismatch')
                row['checks'].append({'id':'notification','status':'PASS'})
            ensure(row['checks'],'Journal contains no restorable captured settings')
        row['status']='PASS'
    except PageSizeUnavailable as error:row.update(status='BLOCKED',reason=str(error),pageSizeAttempts=error.attempts)
    except Blocked as error:row.update(status='BLOCKED',reason=str(error))
    except Exception as error:
        row.update(status='FAIL',exceptionType=type(error).__name__)
        if isinstance(error,ValueError):row['reason']=str(error)
    finally:
        row['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (out/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:row.get(k) for k in ('status','reason','exceptionType','checks')},ensure_ascii=False))
    return 0 if row['status']=='PASS' else 2 if row['status']=='BLOCKED' else 1
if __name__=='__main__':raise SystemExit(main())
