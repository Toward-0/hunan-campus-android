from adb_client import shell
from pathlib import Path
import argparse,json,shlex,datetime
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--label',required=True);a=p.parse_args()
assert a.label.replace('-','').isalnum()
pkg='org.esurfing.hunan';out=[]
def run(name,cmd):
    code,data,_=shell(a.serial,cmd,20);value=data.decode(errors='replace').strip()
    out.append({'query':name,'exitCode':code,'value':value});return value
pid=run('pid','pidof '+pkg);assert pid.isdigit()
run('process-state',f"cat /proc/{pid}/status | awk '/^(Name|State|Threads|Uid):/ {{print}}'")
run('process-runtime',f"dumpsys activity processes {pkg} | awk '/ProcessRecord/ {{s=($0 ~ /org[.]esurfing[.]hunan\//)}} s && /curProcState=|curAdj=|setProcState=|cached=|frozen=|freeze|hasForegroundServices=|mState=/ {{print}}'")
run('runtime-clock','cat /proc/uptime')
run('standby-bucket','am get-standby-bucket '+pkg)
run('power-saver','settings get global low_power')
policy=r'''/Alarm\{/ {s=($0 ~ /org[.]esurfing[.]hunan\}/)} s && /policyWhenElapsed|REQUESTER|APP_STANDBY|DEVICE_IDLE|BATTERY_SAVER/ {print}'''
run('alarm-policy','dumpsys alarm | awk '+shlex.quote(policy))
run('alarms',"dumpsys alarm | awk '/org[.]esurfing[.]hunan([^.]|$)/ && /Alarm\{|type=|when=|whenElapsed=|WakeupReceiver|WAKE_TASK|allowWhileIdle|flags=|pending|Pending/ {print}'")
run('power',"dumpsys power | awk '/mWakefulness=|mWakefulnessChanging=|mIsPowered=|mDeviceIdleMode=|mLightDeviceIdleMode=/ {print}'")
result={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'package':pkg,'queries':out}
(Path(__file__).parent/'evidence'/(a.label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False,indent=2))
