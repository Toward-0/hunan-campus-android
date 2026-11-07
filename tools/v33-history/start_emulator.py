from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
import argparse,os,subprocess,json,time
from adb_client import shell,devices
r=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--api',type=int,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--flavor',default='google_apis',choices=['google_apis','default']);p.add_argument('--instance',default='');a=p.parse_args()
assert a.api in [26,29,31,33,35,36] and a.port in [5554,5556,5558,5560,5562,5564,5566]
assert not any(line.split()[0]==f'emulator-{a.port}' for line in devices().splitlines() if line.strip()),'Requested emulator port is already in use'
image=r/'sdk/system-images'/f'android-{a.api}'/a.flavor/'x86_64'
assert (image/'system.img').exists(),'Verified system image is not installed'
assert not a.instance or a.instance.isalnum()
name=f'campus-s1-api{a.api}'+('-'+a.instance if a.instance else '');avd=r/'avd'/f'{name}.avd';avd.mkdir(parents=True,exist_ok=True)
(r/'avd'/f'{name}.ini').write_text(f'avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-{a.api}\n')
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
tag.id={a.flavor}
tag.display={a.flavor}
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
env=os.environ.copy();env.update(ANDROID_USER_HOME=str(r/'android-user'),ANDROID_EMULATOR_HOME=str(r/'android-user'),ANDROID_PREFS_ROOT=str(r/'android-user'),ANDROID_SDK_HOME=str(r/'legacy-android-home'),ANDROID_AVD_HOME=str(r/'avd'),ANDROID_HOME=str(r/'sdk'),ANDROID_SDK_ROOT=str(r/'sdk'),USERPROFILE=str(r/'java-user'),LOCALAPPDATA=str(r/'local-appdata'),APPDATA=str(r/'appdata'),TEMP=str(r/'tmp'),TMP=str(r/'tmp'))
for path in ['android-user','legacy-android-home','.android','java-user','local-appdata','appdata']:(r/path).mkdir(exist_ok=True)
cmd=[str(r/'sdk/emulator/emulator.exe'),'-avd',name,'-port',str(a.port),'-no-window','-no-audio','-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-accel','on']
with (r/'evidence'/f'emulator-api{a.api}.log').open('wb') as log:
    proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
row={'api':a.api,'flavor':a.flavor,'pid':proc.pid,'serial':f'emulator-{a.port}','command':cmd,'avd':str(avd),'status':'BLOCKED'}
end=time.monotonic()+240
while time.monotonic()<end and proc.poll() is None:
    try:
        code,out,err=shell(row['serial'],'getprop sys.boot_completed',5)
        if out.strip()==b'1':row['status']='PASS';break
    except Exception:pass
    time.sleep(3)
if row['status']!='PASS':
    row['exitCode']=proc.poll()
    if proc.poll() is None:proc.terminate();proc.wait(timeout=15)
else:
    for key,cmd in [('pageSize','getconf PAGE_SIZE'),('abis','getprop ro.product.cpu.abilist')]:row[key]=shell(row['serial'],cmd)[1].decode().strip()
(r/'evidence'/f'emulator-api{a.api}-boot.json').write_text(json.dumps(row,indent=2));print(json.dumps(row),flush=True)
raise SystemExit(0 if row['status']=='PASS' else 1)
