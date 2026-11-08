import argparse,time,json,re,hashlib,datetime
from pathlib import Path
import device_read
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--apk',required=True);p.add_argument('--label',required=True);a=p.parse_args()
assert a.label.replace('-','').isalnum()
device_read.SERIAL=a.serial
root=Path(__file__).parent/'evidence';dest=root/(a.label+'.json');assert not dest.exists()
def event(snapshot):
    values={r['query']:r['value'] for r in snapshot['queries'] if r['exitCode']==0}
    matched=re.fullmatch(r'(\d+) (\d+) (\w+) heartbeat=(\d+):(\w+) internet=(\d+):(\w+)',values['latestEvent'])
    assert matched
    return values,matched.groups()
def trace_rows(value):
    return [{k:json.loads(v) for k,v in re.findall(r'"([A-Za-z]+)":("[A-Z_]+"|[0-9]+|true|false)',line)} for line in value.splitlines()]
report={'testId':'REAL-NETWORK-SHORT','apkSha256':hashlib.sha256(Path(a.apk).read_bytes()).hexdigest().upper(),'package':'org.esurfing.hunan','time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'FAIL','automaticAuthRequests':0,'additionalNetworkProbes':0,'observation':'USB-connected screen-off; only start/end whitelisted snapshots'}
try:
    started=time.monotonic();first=device_read.snapshot(a.label+'-start',False)
    start_values,start=event(first)
    start_elapsed=max((r.get('elapsed',0) for r in trace_rows(start_values['timing'])),default=0)
    assert start[2]=='AUTHENTICATED' and start[4]=='PASS' and start[6]=='PASS'
    report['startEvent']=list(start);report['batteryExempt']=start_values['whitelisted']=='true'
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Observation started; no device polling during the next 310 seconds.',flush=True)
    for _ in range(10):time.sleep(30)
    time.sleep(10)
    final=device_read.snapshot(a.label+'-end',False);values,end=event(final)
    report['endEvent']=list(end);report['durationSeconds']=round(time.monotonic()-started,2)
    trace=trace_rows(values['timing'])
    report['deliveries']=[r for r in trace if r.get('point') in ['TIMER_DELIVERY','ALARM_DELIVERY'] and r.get('generation')==int(start[1]) and r.get('elapsed',0)>start_elapsed]
    assert end[1]==start[1] and end[2]=='AUTHENTICATED' and end[4]=='PASS' and end[6]=='PASS'
    assert int(end[3])>int(start[3]) and int(end[5])>int(start[5])
    assert any(r.get('kind')=='HEARTBEAT' and r.get('interactive') is False for r in report['deliveries'])
    report['status']='PASS'
except Exception as e:report['errorType']=type(e).__name__
finally:
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False),flush=True)
