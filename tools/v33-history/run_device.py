from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
from adb_client import shell,push
import argparse,json,hashlib,datetime,shlex,concurrent.futures,time,xml.etree.ElementTree as ET,re,subprocess,sys
r=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--apk',required=True);p.add_argument('--label',required=True);p.add_argument('--probe',default='CompatProbe');p.add_argument('--mode');p.add_argument('--timeout',type=int,default=180);p.add_argument('--install',action='store_true');a=p.parse_args()
assert a.probe in ['CompatProbe','InternetProbe','StabilityProbe','AlarmProbe','SessionProbe','DiscoveryProbe','RepairMenuProbe']
assert a.mode in [None,'lifecycle','repair','transport','account']
assert 10 <= a.timeout <= 900
assert a.label.replace('-','').isalnum()
apk=Path(a.apk).resolve();assert apk.is_file()
sha=hashlib.sha256(apk.read_bytes()).hexdigest().upper();out=r/'evidence'/a.label;out.mkdir(exist_ok=True)
row={'serial':a.serial,'package':'org.esurfing.hunan.isolation','apk':apk.name,'apkSha256':sha,'testId':a.probe,'mode':a.mode,'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commands':[]}
def run(cmd,timeout=60):
    code,b,e=shell(a.serial,cmd,timeout);row['commands'].append({'adbEquivalent':['adb','-s',a.serial,'shell',cmd],'exitCode':code});return code,b,e
try:
    info=subprocess.run([str(r/'sdk/build-tools/35.0.0/aapt.exe'),'dump','badging',str(apk)],capture_output=True,timeout=15,check=True).stdout.decode(errors='replace')
    assert re.search(r"^package: name='org.esurfing.hunan.isolation' ",info,re.M),'Only the isolation APK is allowed'
    apkabis=re.findall(r"'([^']+)'",next(s for s in info.splitlines() if s.startswith('native-code:')))
    code,b,e=run('getprop ro.product.cpu.abilist');assert code==0
    row['supportedAbis']=b.decode().strip().split(',');assert set(apkabis)&set(row['supportedAbis']),'ABI mismatch'
    for k in ['ro.build.version.sdk','ro.product.model']:
        code,b,e=run('getprop '+k);assert code==0;row[k]=b.decode().strip()
    code,b,e=run('getconf PAGE_SIZE')
    if code==0 and b.strip().isdigit(): row['pageSize']=int(b.strip())
    else:
        code,b,e=run("grep -m 1 '^KernelPageSize:' /proc/self/smaps");assert code==0
        row['pageSize']=int(re.search(rb'([0-9]+) kB',b).group(1))*1024
    if a.install:
        code,b,e=run('pm path org.esurfing.hunan.isolation');row['isolationExisted']=bool(b.strip())
        remote='/data/local/tmp/campus-s1-'+a.label+'.apk';push(a.serial,apk,remote)
        try:
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                pending=pool.submit(run,'pm install -r '+shlex.quote(remote),120)
                for _ in range(30):
                    if pending.done(): break
                    time.sleep(2)
                    _,focus,_=shell(a.serial,'dumpsys window | grep mCurrentFocus',10)
                    if b'com.oplus.appdetail' not in focus: continue
                    # Only inspect the already-observed installer for this synthetic APK.
                    xmlpath='/data/local/tmp/campus-s1-installer.xml'
                    shell(a.serial,'uiautomator dump '+xmlpath,15)
                    _,data,_=shell(a.serial,'cat '+xmlpath,10)
                    shell(a.serial,'rm -f '+xmlpath,10)
                    try: tree=ET.fromstring(data)
                    except ET.ParseError: continue
                    labels=[n.attrib.get('text','') for n in tree.iter('node')]
                    if not any('校园网' in s for s in labels): continue
                    for n in tree.iter('node'):
                        if n.attrib.get('text')=='继续安装':
                            coords=list(map(int,re.findall(r'\d+',n.attrib['bounds'])))
                            shell(a.serial,f'input tap {(coords[0]+coords[2])//2} {(coords[1]+coords[3])//2}',10)
                            row['installerConfirmation']='Observed own-APK Continue Install button clicked'
                            break
                code,b,e=pending.result()
            row['install']={'exitCode':code,'output':b.decode()};assert code==0 and b'Success' in b
        finally: run('rm -f '+shlex.quote(remote))
    code,b,e=run('pm path org.esurfing.hunan.isolation');assert code==0
    installed=b.decode().strip().removeprefix('package:');assert installed.startswith('/data/app/') and installed.endswith('.apk')
    code,b,e=run('sha256sum '+shlex.quote(installed));assert code==0
    row['installedApkSha256']=b.decode().split()[0].upper();assert row['installedApkSha256']==sha
    if int(row['ro.build.version.sdk'])>=33:
        code,b,e=run('pm grant org.esurfing.hunan.isolation android.permission.POST_NOTIFICATIONS')
        row['notificationGrantExit']=code  # OEM may deny shell grants; not a login requirement.
    cmd='am instrument -w -r '+(('-e mode '+shlex.quote(a.mode)+' ') if a.mode else '')+'org.esurfing.hunan.isolation/org.esurfing.hunan.'+a.probe
    code,b,e=run(cmd,a.timeout);(out/'instrumentation.txt').write_bytes(b);(out/'stderr.txt').write_bytes(e)
    assert code==0 and b'INSTRUMENTATION_CODE: -1' in b and b'FAIL' not in b and b'Process crashed' not in b,'Instrumentation did not complete successfully'
    if a.probe=='CompatProbe':
        _,data,_=run('run-as org.esurfing.hunan.isolation cat files/compat-jni.json');(out/'jni.json').write_bytes(data)
        row['result']=json.loads(data);row['status']=row['result']['status']
    else: row['status']='PASS' if code==0 and b'INSTRUMENTATION_CODE: -1' in b and b'FAIL' not in b and b'Process crashed' not in b else 'FAIL'
    if a.probe=='RepairMenuProbe':
        code,b,e=run('run-as org.esurfing.hunan.isolation cat files/repair-menu-result.json');assert code==0
        (out/'menu-cases.json').write_bytes(b)
        assert json.loads(b)['serviceCommands']==0
    if a.probe=='StabilityProbe':
        mode=a.mode or 'lifecycle'
        code,b,e=run('run-as org.esurfing.hunan.isolation cat files/stability-'+mode+'.jsonl');assert code==0
        (out/'cases.jsonl').write_bytes(b)
except Exception as e:
    row['status']='FAIL';row['exception']=type(e).__name__;row['reason']=str(e)
finally:
    # Stop only the isolated test package; never touch the production session.
    cleanupCode,_,_=run('am force-stop org.esurfing.hunan.isolation')
    if cleanupCode!=0:row.update(status='FAIL',cleanupExit=cleanupCode)
    (out/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(row,ensure_ascii=False),flush=True)
sys.exit(0 if row['status']=='PASS' else 1)
