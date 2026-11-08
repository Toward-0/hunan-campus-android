from adb_client import shell, devices
from pathlib import Path
import json, shlex, datetime
SERIAL=None
PACKAGE='org.esurfing.hunan'
STAGE=Path(__file__).parent
def query(name, command):
    code,out,err=shell(SERIAL,command,20)
    return {'query':name,'exitCode':code,'value':out.decode(errors='replace').strip()}
def snapshot(label, verbose=True):
    assert any(x.split()[:2]==[SERIAL,'device'] for x in devices().splitlines())
    commands={
      'model':'getprop ro.product.model', 'api':'getprop ro.build.version.sdk',
      'abis':'getprop ro.product.cpu.abilist', 'pageSize':'getconf PAGE_SIZE',
      'version':f"dumpsys package {PACKAGE} | awk '/versionCode=/ {{print $1}} /versionName=/ {{print $1}}'",
      'idle':'cmd deviceidle get deep',
      'whitelisted':f'cmd deviceidle whitelist ={PACKAGE}',
      'exact':f'cmd appops get {PACKAGE} SCHEDULE_EXACT_ALARM',
      'background':f'cmd appops get {PACKAGE} RUN_ANY_IN_BACKGROUND',
      'notifications':f'cmd appops get {PACKAGE} POST_NOTIFICATION',
      'service':f"dumpsys activity services {PACKAGE} | awk '/ServiceRecord/ {{selected=($0 ~ /org[.]esurfing[.]hunan\\/([.]SessionService|org[.]esurfing[.]hunan[.]SessionService)/)}} selected && /isForeground=/ {{print $1}}'",
    }
    event=r'''BEGIN{FS="\t"} NF==17 && $1~/^[0-9]+$/ && $3~/^[0-9]+$/ && $6~/^[0-9]+$/ && $8~/^[0-9]+$/ && $7~/^(UNKNOWN|PASS|FAIL)$/ && $9~/^(UNKNOWN|PASS|FAIL)$/ && $5~/^(IDLE|WAITING_WIFI|DISCOVERING|LOGGING_OUT|AUTHENTICATING|AUTHENTICATED|RECOVERING|NEEDS_INPUT|STOPPED|LOGGED_OUT|LOGOUT_UNCONFIRMED|INTERRUPTED|REPAIRING)$/ {last=$1 " " $3 " " $5 " heartbeat=" $6 ":" $7 " internet=" $8 ":" $9} END{print last}'''
    commands['latestEvent']='run-as '+PACKAGE+' sh -c '+shlex.quote('awk '+shlex.quote(event)+' no_backup/diagnostics/events.tsv')
    trace=r'''{line=$0; out=""; n=split("point kind elapsed dueElapsed task generation idle interactive plugged schedulerMode error number batteryExempt exactAllowed notificationsAllowed",keys," "); for(i=1;i<=n;i++){pat="\"" keys[i] "\":(\"[A-Z_]+\"|[0-9]+|true|false)"; if(match(line,pat))out=out substr(line,RSTART,RLENGTH) " "} if(out!="")print out}'''
    commands['timing']='run-as '+PACKAGE+' sh -c '+shlex.quote('for f in no_backup/timing-v2/trace.previous.jsonl no_backup/timing-v2/trace.jsonl; do if [ -f "$f" ]; then awk '+shlex.quote(trace)+' "$f"; fi; done | tail -n 120')
    result={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'device':'RMX3820','package':PACKAGE,'queries':[query(k,v) for k,v in commands.items()]}
    dest=STAGE/'evidence'/f'{label}.json';dest.parent.mkdir(exist_ok=True);dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if verbose:print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--label',required=True);a=p.parse_args()
    assert a.label.replace('-','').isalnum()
    SERIAL=a.serial
    snapshot(a.label)
