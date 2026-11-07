"""Install or collect reviewed fixed-schema fields. Never sends start/logout/repair."""
from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
from adb_client import devices,shell,push
import argparse,json,hashlib,shlex,datetime,concurrent.futures,time,re,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--package',required=True,choices=['org.esurfing.hunan']);p.add_argument('--apk',required=True);p.add_argument('--mode',required=True,choices=['install','collect']);p.add_argument('--label',required=True);a=p.parse_args()
assert re.fullmatch('[A-Za-z0-9-]+',a.label)
apk=Path(a.apk).resolve();assert apk.name=='ESurfingHunan-0.2.21-compat-s1-candidate-phone.apk'
sha=hashlib.sha256(apk.read_bytes()).hexdigest().upper()
assert any(line.split()[:2]==[a.serial,'device'] for line in devices().splitlines()),'Explicit device is not online'
out=R/'evidence'/a.label;out.mkdir(exist_ok=False)
row={'time':datetime.datetime.now().astimezone().isoformat(),'serial':a.serial,'package':a.package,'apkSha256':sha,'mode':a.mode,'commands':[],'automaticLoginCount':0,'logoutCount':0,'networkProbes':0}
def run(command,timeout=20):
    code,b,e=shell(a.serial,command,timeout)
    row['commands'].append({'adbEquivalent':['adb','-s',a.serial,'shell',command],'exitCode':code})
    return code,b,e
def installed_hash():
    c,b,e=run('pm path '+a.package);assert c==0
    path=b.decode().strip().removeprefix('package:');assert re.fullmatch(r'/data/app/[A-Za-z0-9_./~=+-]+\.apk',path)
    c,b,e=run('sha256sum '+shlex.quote(path));assert c==0
    return b.decode().split()[0].upper()
try:
    row['beforeApkSha256']=installed_hash()
    if a.mode=='install':
        assert row['beforeApkSha256'] in ['2BD69D4E3ED9F8C0D183732561125E52108968A708B0230E049E3E1C928057CA','1DC66CFE310CD6C47DC83DE0ED82E49E26C9BE838779BCA28F90DC4BA3F781E6','B98713E7A8C9578357F180CE97499E7DC7BF21AE42052A728058A403748191C2',sha], 'Unreviewed installed APK'
        remote='/data/local/tmp/campus-s1-account-fix-main.apk';push(a.serial,apk,remote)
        try:
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                pending=pool.submit(run,'pm install -r '+remote,120)
                for _ in range(30):
                    if pending.done():break
                    time.sleep(2)
                    _,focus,_=shell(a.serial,'dumpsys window | grep mCurrentFocus',10)
                    if b'com.oplus.appdetail' not in focus:continue
                    # Inspect only the visible installer, never the account screen.
                    xmlpath='/data/local/tmp/campus-s1-installer.xml'
                    run('uiautomator dump '+xmlpath,15);c,data,e=run('cat '+xmlpath);run('rm -f '+xmlpath)
                    try: tree=ET.fromstring(data)
                    except ET.ParseError:continue
                    nodes=list(tree.iter('node'))
                    if not any('校园网' in n.attrib.get('text','') for n in nodes):continue
                    for n in nodes:
                        if n.attrib.get('text')=='继续安装':
                            x1,y1,x2,y2=map(int,re.findall(r'\d+',n.attrib['bounds']))
                            run(f'input tap {(x1+x2)//2} {(y1+y2)//2}');row['installerConfirmed']=True;break
                c,b,e=pending.result();assert c==0 and b'Success' in b
                row['installExit']=c
        finally:run('rm -f '+remote)
    row['afterApkSha256']=installed_hash();assert row['afterApkSha256']==sha
    for name,cmd in [('version',"dumpsys package org.esurfing.hunan | grep -E 'versionCode=|versionName=|primaryCpuAbi='"),('api','getprop ro.build.version.sdk'),('model','getprop ro.product.model'),('abis','getprop ro.product.cpu.abilist'),('pageSize','getconf PAGE_SIZE'),('pid','pidof org.esurfing.hunan')]:
        c,b,e=run(cmd);row[name]=b.decode().strip()
    if a.mode=='collect':
        # Writers were source-reviewed: fixed enums/numbers only, no raw logs/vault/preferences.
        for name,cmd in [('events.tsv','run-as org.esurfing.hunan tail -n 150 no_backup/diagnostics/events.tsv'),('timing.jsonl','run-as org.esurfing.hunan tail -n 250 no_backup/timing-v2/trace.jsonl')]:
            c,b,e=run(cmd);assert c==0;(out/name).write_bytes(b)
    row['status']='PASS'
except Exception as e:
    row['status']='FAIL';row['errorType']=type(e).__name__;raise
finally:
    (out/'result.json').write_text(json.dumps(row,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in row.items() if k!='commands'},ensure_ascii=True),flush=True)
