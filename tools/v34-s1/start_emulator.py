"""Start only a fresh revision AVD using a verified, read-only system image."""
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import devices, shell, query_page_size, PageSizeUnavailable
from emulator_process_guard import snapshot_emulator_processes, wait_recorded_processes_exit, terminate_verified_processes
from pathlib import Path
import argparse, os, subprocess, json, time, shutil, threading, re, hashlib

r=require_mutable_stage()
p=argparse.ArgumentParser();p.add_argument('--api',type=int,required=True,choices=[26,29,31,33,35,36]);p.add_argument('--port',type=int,required=True,choices=[5554,5556,5558,5560,5562,5564]);p.add_argument('--label',default=time.strftime('%Y%m%d-%H%M%S'));a=p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9-]+',a.label):raise ValueError('Invalid evidence label')
evidence=assert_stage_write(r/'evidence'/f'emulator-api{a.api}-boot-{a.label}.json')
if evidence.exists():raise RuntimeError('Keep prior evidence; choose a new label')
flavor='google_apis' if a.api in (26,29,35) else 'default'
image=Path('D:/codex/2026-11-06/d-codex-2026-11-05-jian-3/work/compat-s1-20261106-01/sdk/system-images')/f'android-{a.api}'/flavor/'x86_64'
assert (image/'system.img').is_file()
properties=(image/'source.properties').read_text(encoding='utf-8')
def image_property(name):
    match=re.search(r'^'+re.escape(name)+r'\s*=\s*(.+)$',properties,re.M)
    if not match:raise RuntimeError('Missing system image property')
    return match.group(1).strip()
if image_property('AndroidVersion.ApiLevel')!=str(a.api) or image_property('SystemImage.Abi')!='x86_64':raise RuntimeError('System image API/ABI mismatch')
serial=f'emulator-{a.port}'
assert serial not in [v.split()[0] for v in devices().splitlines() if v.strip()], 'Port already has a device'
assert shutil.disk_usage(r).free > 10*1024**3, 'Keep at least 10 GiB free before AVD creation'
name=f's1-json-ui-api{a.api}'
avd=assert_stage_write(r/'avd'/(name+'.avd'));avd.mkdir(exist_ok=True)
assert_stage_write(r/'avd'/(name+'.ini')).write_text(f'avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-{a.api}\n')
assert_stage_write(avd/'config.ini').write_text(f'''AvdId={name}
avd.ini.encoding=UTF-8
abi.type=x86_64
hw.cpu.arch=x86_64
hw.cpu.ncore=2
hw.ramSize=2048
hw.lcd.width=1080
hw.lcd.height=2340
hw.lcd.density=480
hw.gpu.enabled=yes
hw.gpu.mode=swiftshader_indirect
image.sysdir.1={image}
tag.id={flavor}
tag.display={flavor}
disk.dataPartition.size=2G
fastboot.forceColdBoot=yes
PlayStore.enabled=false
hw.keyboard=no
hw.battery=yes
skin.dynamic=yes
showDeviceFrame=no
hw.mainKeys=no
hw.sdCard=no
''')
env=os.environ.copy()
env.update(ANDROID_USER_HOME=str(r/'android-user'),ANDROID_EMULATOR_HOME=str(r/'android-user'),ANDROID_AVD_HOME=str(r/'avd'),ANDROID_HOME=str(r/'sdk'),ANDROID_SDK_ROOT=str(r/'sdk'),USERPROFILE=str(r/'java-user'),LOCALAPPDATA=str(r/'local-appdata'),APPDATA=str(r/'appdata'),TEMP=str(r/'tmp'),TMP=str(r/'tmp'))
env.pop('ANDROID_PREFS_ROOT',None);env.pop('ANDROID_SDK_HOME',None)
tools=json.loads((r/'tools.local.json').read_text(encoding='utf-8-sig'))
cmd=[tools['EmulatorExecutable'],'-avd',name,'-port',str(a.port),'-no-window','-no-audio','-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-accel','on']
row={'testId':f'ENV-API{a.api}','api':a.api,'flavor':flavor,'deviceAlias':serial,'command':cmd,'avd':str(avd),'image':str(image),'status':'BLOCKED','startedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'toolMessages':[]}
row['systemImagePropertiesSha256']=hashlib.sha256((image/'source.properties').read_bytes()).hexdigest().upper()
proc=None
def stop_started_process():
    if proc is None:return
    try:
        process_tree=row.get('processTree',[])
        current_tree=[x for x in snapshot_emulator_processes(name,serial,tools['EmulatorExecutable']) if x['pid']==proc.pid or x['parentPid']==proc.pid]
        process_tree=list({x['pid']:x for x in process_tree+current_tree}.values())
        row['processTree']=process_tree
        online=any(line.split()[0]==serial for line in devices().splitlines() if line.strip())
        if online:
            qcode,qemu,_=shell(serial,'getprop ro.kernel.qemu',5)
            ncode,live_name,_=shell(serial,'getprop ro.kernel.qemu.avd_name',5)
            if not live_name.strip():ncode,live_name,_=shell(serial,'getprop ro.boot.qemu.avd_name',5)
            if qcode==0 and ncode==0 and qemu.strip()==b'1' and live_name.decode().strip()==name:
                row['cleanupVerifiedAvd']=name
                try:
                    code,_,_=shell(serial,'reboot -p',10);row['cleanupPowerOffExit']=code
                except (EOFError,OSError):row['cleanupPowerOffConnectionClosed']=True
            else:
                row['cleanupStatus']='BLOCKED';row['cleanupReason']='Live device identity not verified for shutdown'
        if proc.poll() is None:proc.terminate();proc.wait(timeout=15)
        row['cleanupProcessExit']=proc.returncode
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if not any(line.split()[0]==serial for line in devices().splitlines() if line.strip()):
                row['cleanupDeviceDisconnected']=True;break
            time.sleep(1)
        else:
            row['cleanupDeviceDisconnected']=False;row['cleanupStatus']='BLOCKED'
            row['cleanupReason']='Launcher exit did not establish emulator disconnection'
        tree_exit=wait_recorded_processes_exit(process_tree,10)
        if tree_exit['status']!='PASS':
            row['exactProcessTerminations']=terminate_verified_processes(process_tree)
            tree_exit=wait_recorded_processes_exit(process_tree,10)
        row['cleanupProcessTreeExit']=tree_exit
        if row.get('cleanupDeviceDisconnected') and tree_exit['status']=='PASS':row['cleanupStatus']='PASS'
        else:row['cleanupStatus']='BLOCKED'
    except Exception as cleanup_error:
        row['cleanupStatus']='BLOCKED'
        row['cleanupExceptionType']=type(cleanup_error).__name__
try:
    proc=subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    row['pid']=proc.pid
    # Tool diagnostics only: never collect guest logcat or credential-bearing output.
    def read_tool_messages():
        for raw in iter(proc.stdout.readline,b''):
            line=raw.decode(errors='replace').strip()
            if any(x in line.lower() for x in ('whpx','hypervisor','not enough space','insufficient','error:','panic:','boot completed')) and not any(x in line.lower() for x in ('token','key','credential')):
                if len(row['toolMessages'])<200:row['toolMessages'].append(line[:400])
    reader=threading.Thread(target=read_tool_messages,daemon=True);reader.start()
    end=time.monotonic()+240
    row['bootPollChanges']=[]
    previous_poll=None
    while time.monotonic()<end and proc.poll() is None:
        poll={'elapsedSeconds':round(240-(end-time.monotonic()),1)}
        try:
            selected=[line.split() for line in devices().splitlines() if line.strip() and line.split()[0]==serial]
            state=selected[0][1] if len(selected)==1 and len(selected[0])>1 else 'absent'
            poll['transportState']=state if state in ('device','offline','unauthorized','authorizing','absent') else 'other'
            if state=='device':
                code,b,_=shell(serial,'getprop sys.boot_completed',5)
                poll['shellExitCode']=code
                poll['bootProperty']=b.decode().strip() if b.strip() in (b'',b'0',b'1') else 'NON_SCHEMA'
                if code==0 and b.strip()==b'1':row['bootCompleted']=True
        except (OSError,EOFError,RuntimeError) as error:
            poll['exceptionType']=type(error).__name__
            message=str(error).lower()
            poll['failureKind']=next((key for key in ('unauthorized','offline','not found','closed','timeout') if key in message),'transport-error')
        signature={k:v for k,v in poll.items() if k!='elapsedSeconds'}
        if signature!=previous_poll:
            row['bootPollChanges'].append(poll);previous_poll=signature
            progress=assert_stage_write(evidence.with_name(evidence.stem+'-progress.json'))
            progress.write_text(json.dumps(row,indent=2),encoding='utf-8')
        if not any(x['parentPid']==proc.pid for x in row.get('processTree',[])):
            row['processTree']=[x for x in snapshot_emulator_processes(name,serial,tools['EmulatorExecutable']) if x['pid']==proc.pid or x['parentPid']==proc.pid]
        if row.get('bootCompleted'):break
        time.sleep(3)
    if row.get('bootCompleted'):
        row['lastCheck']='page-size'
        page=query_page_size(serial)
        row['pageSize']=str(page['pageSize']);row['pageSizeEvidence']=page
        row['environmentChecks']=[]
        for key,command in [('abis','getprop ro.product.cpu.abilist'),('qemu','getprop ro.kernel.qemu'),('actualApi','getprop ro.build.version.sdk')]:
            row['lastCheck']=key
            code,b,_=shell(serial,command,10)
            row['environmentChecks'].append({'field':key,'exitCode':code})
            if code!=0:raise RuntimeError('Environment query returned nonzero: '+key)
            value=b.decode().strip()
            if key=='abis' and not re.fullmatch(r'[A-Za-z0-9_,.-]+',value):raise RuntimeError('Invalid ABI field')
            if key in ('qemu','actualApi') and not value.isdigit():raise RuntimeError('Invalid numeric environment field: '+key)
            row[key]=value
        if row['qemu']!='1':raise RuntimeError('Selected device is not an emulator')
        if row['actualApi']!=str(a.api) or 'x86_64' not in row['abis'].split(','):raise RuntimeError('Actual emulator API/ABI mismatch')
        row['status']='PASS'
    else:
        row['exitCode']=proc.poll()
        stop_started_process()
except PageSizeUnavailable as ex:
    row.update(status='BLOCKED',reason=str(ex),pageSizeAttempts=ex.attempts)
    stop_started_process()
except Exception as ex:
    row['status']='FAIL'
    row['exceptionType']=type(ex).__name__
    if isinstance(ex,RuntimeError):row['reason']=str(ex)
    stop_started_process()
evidence.write_text(json.dumps(row,indent=2),encoding='utf-8')
print(json.dumps(row),flush=True)
raise SystemExit(0 if row['status']=='PASS' else 1)
