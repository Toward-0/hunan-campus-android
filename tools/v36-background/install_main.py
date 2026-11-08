from pathlib import Path
from adb_client import shell,push,devices
import argparse,hashlib,json,shlex,datetime,re
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--package',required=True,choices=['org.esurfing.hunan']);p.add_argument('--apk',required=True);p.add_argument('--sha256',required=True);p.add_argument('--version',required=True,type=int);p.add_argument('--label',required=True);a=p.parse_args()
apk=Path(a.apk).resolve(strict=True);package=a.package
assert hashlib.sha256(apk.read_bytes()).hexdigest().upper()==a.sha256.upper()
report={'testId':'REALME-INSTALL','time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'apkSha256':a.sha256.upper(),'package':package,'status':'FAIL','commands':[]}
assert a.label.replace('-','').isalnum() and a.version>=35
dest=Path(__file__).parent/'evidence'/f'{a.label}.json';assert not dest.exists()
def run(name,cmd,timeout=20):
    code,data,_=shell(a.serial,cmd,timeout);report['commands'].append({'id':name,'exitCode':code});assert code==0,name
    return data.decode(errors='replace').strip()
def idle():
    awk=r'''BEGIN{FS="\t"} NF==17{a=$2;b=$5} END{if(a=="false" && b~/^(STOPPED|LOGGED_OUT|LOGOUT_UNCONFIRMED|NEEDS_INPUT|INTERRUPTED|IDLE)$/)print "stopped";else print "active-or-unknown"}'''
    assert run('stopped-state','run-as '+package+' sh -c '+shlex.quote('awk '+shlex.quote(awk)+' no_backup/diagnostics/events.tsv'))=='stopped'
    service=r'''/ServiceRecord/ && /org[.]esurfing[.]hunan\/([.]SessionService|org[.]esurfing[.]hunan[.]SessionService)/{n++} END{print n+0}'''
    assert run('service-absent','dumpsys activity services '+package+' | awk '+shlex.quote(service))=='0'
remote='/data/local/tmp/campus-s1-background-main.apk';uploaded=False;finished=False
try:
    assert any(x.split()[:2]==[a.serial,'device'] for x in devices().splitlines())
    assert run('model','getprop ro.product.model')=='RMX3820'
    idle()
    push(a.serial,apk,remote);uploaded=True;idle()
    value=run('install-r','pm install -r '+remote,120);finished=True;assert value=='Success'
    installed=run('installed-path','pm path '+package).removeprefix('package:')
    report['installedSha256']=run('installed-sha','sha256sum '+shlex.quote(installed)).split()[0].upper()
    assert report['installedSha256']==a.sha256.upper()
    report['version']=run('version',f"dumpsys package {package} | awk '/versionCode=/ {{print $1}} /versionName=/ {{print $1}}'")
    assert ('versionCode='+str(a.version)+'\n') in report['version']
    report['status']='PASS'
finally:
    if uploaded and finished:report['cleanup']=run('remove-upload','rm -f '+remote)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
