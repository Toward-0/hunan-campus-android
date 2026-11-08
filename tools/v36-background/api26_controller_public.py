"""Own one fresh API26 AVD, keep its Popen handle, and shut down only that AVD."""
from pathlib import Path
import os, sys, subprocess, socket, time, json, datetime, hashlib, threading, argparse

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stage-root', required=True, help='New writable run directory; preserve earlier runs')
parser.add_argument('--sdk-root', required=True, help='Existing SDK containing emulator and API26 google_apis x86_64 image')
parser.add_argument('--port', required=True, type=int, help='Unused even emulator console port')
args=parser.parse_args()
assert 1024 <= args.port <= 65534 and args.port % 2 == 0
port=args.port
stage=Path(args.stage_root).resolve()
sdk=Path(args.sdk_root).resolve(strict=True)
stage.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from adb_client import shell, devices, query_page_size

image = sdk / 'system-images/android-26/google_apis/x86_64'
name = f'keepalive-api26-{port}'
serial = f'emulator-{port}'
avdroot = stage / 'avd'
avd = avdroot / (name + '.avd')
record = stage / 'evidence/api26-controller.json'
stop = stage / f'STOP_API26_{port}'
# Refuse a second invocation before entering the cleanup/persistence block.
# It must not rewrite evidence belonging to the live or completed first run.
if record.exists() or avd.exists() or stop.exists():
    raise RuntimeError('Preserve prior controller/AVD; create a separate run for another test')
row = {'testId':'ENV-API26', 'status':'BLOCKED', 'serial':serial, 'avdName':name,
       'avd':str(avd), 'image':str(image), 'api':26,
       'startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'toolEvents':[]}
proc = None

def persist():
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf8')

def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1',port)) == 0

def value(prop):
    code,out,err = shell(serial, 'getprop ' + prop, 8)
    if code: raise RuntimeError('property query failed: ' + prop)
    return out.decode().strip()

def identity():
    actual = {'api':value('ro.build.version.sdk'), 'qemu':value('ro.kernel.qemu'),
              'avdName':value('ro.kernel.qemu.avd_name') or value('ro.boot.qemu.avd_name')}
    if actual != {'api':'26','qemu':'1','avdName':name}: raise RuntimeError('AVD identity mismatch')
    return actual

try:
    assert not record.exists() and not avd.exists() and not stop.exists(), 'Preserve prior controller/AVD'
    assert not listening(port) and not listening(port+1), 'Dedicated ports are already occupied'
    assert not any(line.split()[0]==serial for line in devices().splitlines() if line.strip()), 'Dedicated device already exists'
    for filename in ('system.img','userdata.img','vendor.img','ramdisk.img','kernel-ranchu'):
        assert (image/filename).is_file(), 'Missing image component'
    properties = (image/'source.properties').read_text()
    assert 'AndroidVersion.ApiLevel=26' in properties and 'SystemImage.Abi=x86_64' in properties
    row['imagePropertiesSha256'] = hashlib.sha256((image/'source.properties').read_bytes()).hexdigest().upper()
    avd.mkdir(parents=True)
    (avdroot/(name+'.ini')).write_text(f'avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-26\n')
    (avd/'config.ini').write_text(f'''AvdId={name}
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
tag.id=google_apis
tag.display=google_apis
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
    scoped = {'ANDROID_USER_HOME':'api26-user','ANDROID_EMULATOR_HOME':'api26-user',
              'ANDROID_AVD_HOME':'avd','USERPROFILE':'api26-profile','LOCALAPPDATA':'api26-local-appdata',
              'APPDATA':'api26-appdata','TEMP':'api26-tmp','TMP':'api26-tmp'}
    for key, relative in scoped.items():
        destination=stage/relative; destination.mkdir(parents=True, exist_ok=True); env[key]=str(destination)
    env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    env.pop('ANDROID_PREFS_ROOT',None);env.pop('ANDROID_SDK_HOME',None)
    cmd=[str(sdk/'emulator/emulator.exe'),'-avd',name,'-port',str(port),'-no-window','-no-audio',
         '-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-accel','on',
         '-datadir',str(avd),'-data',str(avd/'userdata-qemu.img'),'-cache',str(avd/'cache.img')]
    row['command']=cmd
    proc=subprocess.Popen(cmd,env=env,cwd=str(stage),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    row['pid']=proc.pid;persist()
    def diagnostics():
        for raw in iter(proc.stdout.readline,b''):
            line=raw.decode(errors='replace').strip()
            if any(word in line.lower() for word in ('whpx','hypervisor','error:','panic:','boot completed','insufficient')) and not any(word in line.lower() for word in ('token','key','credential')):
                if len(row['toolEvents'])<80: row['toolEvents'].append(line[:300])
    threading.Thread(target=diagnostics,daemon=True).start()
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        if proc.poll() is not None: raise RuntimeError('Emulator process exited before boot')
        try:
            if value('sys.boot_completed')=='1': break
        except (RuntimeError, EOFError, OSError): pass
        time.sleep(3)
    else: raise RuntimeError('Boot timeout')
    row['runtimeIdentity']=identity()
    row['abi']=value('ro.product.cpu.abilist')
    row['pageSizeEvidence']=query_page_size(serial)
    row['status']='PASS';row['state']='READY';persist()
    print(json.dumps({'state':'READY','serial':serial,'pid':proc.pid,'api':26,'abi':row['abi'],'pageSize':row['pageSizeEvidence']['pageSize']}),flush=True)
    deadline=time.monotonic()+7200
    while not stop.exists() and time.monotonic()<deadline and proc.poll() is None:
        time.sleep(1)
    row['stopRequested']=stop.exists()
except Exception as error:
    row['status']='BLOCKED';row['exception']=type(error).__name__;row['reason']=str(error)
    print(json.dumps({'state':'BLOCKED','reason':str(error)}),flush=True)
finally:
    if proc is not None:
        row['cleanup']={}
        try:
            identity()
            row['cleanup']['identityVerified']=True
            try:
                code,_,_=shell(serial,'reboot -p',10)
                row['cleanup']['powerOffExit']=code
            except (OSError,EOFError): row['cleanup']['powerOffClosedConnection']=True
        except Exception as error:
            row['cleanup']['identityFailure']=type(error).__name__
        try: proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            # Only the process handle created above, never process-name or PID discovery.
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: row['cleanup']['popenWaitTimedOut']=True
        row['cleanup']['popenExitCode']=proc.poll()
        row['cleanup']['consolePortClosed']=not listening(port)
        row['cleanup']['adbPortClosed']=not listening(port+1)
        row['cleanup']['status']='PASS' if proc.poll() is not None and row['cleanup']['consolePortClosed'] and row['cleanup']['adbPortClosed'] else 'BLOCKED'
        row['state']='STOPPED' if row['cleanup']['status']=='PASS' else 'CLEANUP_BLOCKED'
    persist()
    print(json.dumps({'state':row.get('state'),'cleanup':row.get('cleanup')}),flush=True)
