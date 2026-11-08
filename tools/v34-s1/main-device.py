"""Main APK install-r and fixed-field snapshots; never authenticates or stops the app."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import devices, shell, push
import argparse, datetime, hashlib, json, os, re, shlex, subprocess, time

PACKAGE='org.esurfing.hunan'
CERT='2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229'
INACTIVE={'IDLE','NEEDS_INPUT','STOPPED','LOGGED_OUT','LOGOUT_UNCONFIRMED','INTERRUPTED'}
EVENT_AWK=r'''
BEGIN { FS="\t"; valid=0; invalid=0; lastvalid=0 }
NF {
 lastvalid=0
 if (NF!=17 || $2!~/^(true|false)$/ || $5!~/^(IDLE|WAITING_WIFI|DISCOVERING|LOGGING_OUT|AUTHENTICATING|AUTHENTICATED|RECOVERING|NEEDS_INPUT|STOPPED|LOGGED_OUT|LOGOUT_UNCONFIRMED|INTERRUPTED|REPAIRING)$/ || $7!~/^(UNKNOWN|PASS|FAIL)$/ || $9!~/^(UNKNOWN|PASS|FAIL)$/ || $10!~/^(NONE|NETWORK|PROTOCOL|CREDENTIAL_STORAGE|CONFIGURATION|HEARTBEAT|PROCESS_INTERRUPTED|IDLE_WAIT)$/ || $17!~/^(NOT_CHECKED|HTTPS_VERIFIED|PORTAL_REQUIRED|HTTPS_UNREACHABLE)$/) { invalid++; next }
 bad=0
 split("1 3 6 8 11 12 13 14 15",indexes," ")
 for (i in indexes) { v=$(indexes[i]); if(v!~/^[0-9]+$/ || length(v)>16)bad=1 }
 if(bad){invalid++;next}
 valid++;lastvalid=1
 last=sprintf("{\"wall\":%s,\"desired\":%s,\"generation\":%s,\"phase\":\"%s\",\"heartbeatAt\":%s,\"heartbeatResult\":\"%s\",\"internetAt\":%s,\"internetResult\":\"%s\",\"error\":\"%s\",\"retries\":%s,\"nextRecoveryAt\":%s,\"heartbeatDueAt\":%s,\"heartbeatDelayMs\":%s,\"durationMs\":%s,\"internetEvidence\":\"%s\"}",$1,$2,$3,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$17)
}
END { printf "{\"validRowsInCurrentFile\":%d,\"invalidRowsInCurrentFile\":%d,\"lastEvent\":%s}\n",valid,invalid,lastvalid?last:"null" }
'''
MANUAL_AWK=r'''
BEGIN{v="UNKNOWN";n=0}
/<boolean name="manualOff" value="true"[ ]*\/>/ {v="true";n++}
/<boolean name="manualOff" value="false"[ ]*\/>/ {v="false";n++}
END{if(n==1)print v;else print "UNKNOWN"}
'''
class Blocked(RuntimeError): pass
def ensure(value,message):
    if not value:raise ValueError(message)
def main():
    stage=require_mutable_stage()
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('serial','package','apk','sha256','source-id','label'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--expected-api',type=int,required=True)
    parser.add_argument('--version',type=int,required=True)
    parser.add_argument('--mode',choices=['install','snapshot','preflight'],required=True)
    parser.add_argument('--timeout',type=int,default=120)
    a=parser.parse_args()
    ensure(a.package==PACKAGE,'Main package must be explicit')
    ensure(re.fullmatch(r'[A-Za-z0-9-]+',a.label),'Invalid label')
    ensure(re.fullmatch(r'[A-Za-z0-9._-]+',a.source_id),'Invalid source identifier')
    ensure(re.fullmatch(r'[a-fA-F0-9]{64}',a.sha256),'Invalid SHA256')
    ensure(30<=a.timeout<=180 and a.version>33,'Invalid timeout/version')
    out=assert_stage_write(stage/'evidence'/a.label)
    ensure(not out.exists(),'Keep earlier evidence; choose another label');out.mkdir()
    row={'testId':'MAIN-'+a.mode.upper(),'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'sourceId':a.source_id,'package':PACKAGE,'targetVersion':a.version,'apkSha256':a.sha256.upper(),
         'status':'FAIL','commands':[],'automaticLoginCount':0,'automaticLogoutCount':0,
         'automaticRepairCount':0,'additionalNetworkProbeCount':0,'mainForceStopCount':0,'mainDataClearCount':0}
    def run(name,command,timeout=15):
        code,data,_=shell(a.serial,command,timeout)
        row['commands'].append({'id':name,'exitCode':code})
        ensure(code==0,'Device command failed: '+name)
        return data.decode('utf-8',errors='strict').strip()
    def prop(key):return run('property-'+key,'getprop '+key)
    def installed():
        value=run('installed-package-path','pm path '+PACKAGE)
        ensure(re.fullmatch(r'package:/data/app/[A-Za-z0-9_./~=+-]+\.apk',value),'Expected one installed main APK')
        digest=run('installed-apk-hash','sha256sum '+shlex.quote(value[8:])).split()[0].upper()
        ensure(re.fullmatch(r'[A-F0-9]{64}',digest),'Invalid installed digest')
        awk=r'/^[[:space:]]*versionCode=[0-9]+/ { split($1,a,"="); print a[2]; n++ } END{if(n!=1)exit 2}'
        version=run('installed-version','set -o pipefail; dumpsys package '+PACKAGE+' | awk '+shlex.quote(awk))
        ensure(re.fullmatch(r'[0-9]+',version),'Invalid installed version')
        return {'versionCode':int(version),'apkSha256':digest}
    def snapshot(name):
        manual_cmd='awk '+shlex.quote(MANUAL_AWK)+' shared_prefs/settings.xml'
        manual=run(name+'-manual-off','run-as '+PACKAGE+' sh -c '+shlex.quote(manual_cmd))
        ensure(manual in ('true','false','UNKNOWN'),'Unexpected manualOff state')
        event_cmd='awk '+shlex.quote(EVENT_AWK)+' no_backup/diagnostics/events.tsv'
        summary=json.loads(run(name+'-events','run-as '+PACKAGE+' sh -c '+shlex.quote(event_cmd)))
        service_awk=r'BEGIN{s=0} /ServiceRecord/ && /org[.]esurfing[.]hunan\/([.]SessionService|org[.]esurfing[.]hunan[.]SessionService)/{s=1} END{print s?"true":"false"}'
        service=run(name+'-service-presence','set -o pipefail; dumpsys activity services '+PACKAGE+' | awk '+shlex.quote(service_awk))
        ensure(service in ('true','false'),'Unknown service state')
        return {'manualOff':manual,'sessionServicePresent':service=='true','events':summary}
    def require_idle(state):
        latest=state['events'].get('lastEvent')
        if state['manualOff']!='true' or state['sessionServicePresent'] or not latest or latest['desired'] or latest['phase'] not in INACTIVE:
            raise Blocked('Main session is active or idle state is unproven; user must manually stop and retry after confirmation')
    try:
        apk=Path(a.apk).resolve(strict=True)
        ensure(hashlib.sha256(apk.read_bytes()).hexdigest().upper()==a.sha256.upper(),'Local APK hash mismatch')
        tools=json.loads((stage/'tools.local.json').read_text(encoding='utf-8-sig'))
        ensure(Path(os.environ.get('JAVA_HOME','')).resolve()==Path(tools['JdkHome']).resolve(),'Initialize stage-env before this script')
        metadata=subprocess.run([str(stage/'sdk/build-tools/35.0.0/aapt.exe'),'dump','badging',str(apk)],capture_output=True,timeout=20)
        row['localMetadataExit']=metadata.returncode
        ensure(metadata.returncode==0,'APK metadata tool failed')
        meta=metadata.stdout.decode(errors='replace')
        ensure(re.search(r"package: name='"+re.escape(PACKAGE)+r"' versionCode='"+str(a.version)+r"'",meta),'Target APK package/version mismatch')
        apk_abis=set(re.findall(r"'([^']+)'",next(v for v in meta.splitlines() if v.startswith('native-code:'))))
        ensure(apk_abis=={'arm64-v8a','armeabi-v7a'},'Main APK must contain exactly two ARM ABIs')
        verification=subprocess.run([str(Path(tools['JdkHome'])/'bin/java.exe'),'-XX:-UsePerfData',
            '-Djava.io.tmpdir='+str(stage/'tmp'),'-Duser.home='+str(stage/'java-user'),'-jar',
            str(stage/'sdk/build-tools/35.0.0/lib/apksigner.jar'),'verify','--print-certs',str(apk)],capture_output=True,timeout=30)
        certs={x.lower() for x in re.findall(r'certificate SHA-256 digest:\s*([a-fA-F0-9]{64})',verification.stdout.decode(errors='replace'))}
        row['signature']={'exitCode':verification.returncode,'certificateSha256':sorted(certs)}
        ensure(verification.returncode==0 and certs=={CERT},'Target APK signature mismatch')
        online=[v.split() for v in devices().splitlines() if v.strip() and v.split()[0]==a.serial]
        if len(online)!=1 or online[0][1]!='device':raise Blocked('Explicit device is offline or unauthorized')
        model=prop('ro.product.model');api=int(prop('ro.build.version.sdk'))
        qemu=prop('ro.kernel.qemu');abis=prop('ro.product.cpu.abilist').split(',')
        ensure(model in ('RMX3820','V2307A') and qemu!='1','Device outside confirmed physical-phone scope')
        ensure(api==a.expected_api and bool(apk_abis.intersection(abis)),'Device API/ABI mismatch')
        row.update(deviceAlias=model,model=model,api=api,supportedAbis=abis,pageSize=int(run('page-size','getconf PAGE_SIZE')))
        before=installed();row['beforeInstall']=before
        if before['versionCode']>a.version:raise Blocked('Installed version is newer; no downgrade is allowed')
        if a.mode in ('install','preflight'):
            try:row['beforeState']=snapshot('before-install')
            except (ValueError,RuntimeError,KeyError,json.JSONDecodeError) as error:
                raise Blocked('Cannot prove main session is safely stopped from whitelisted state') from error
            require_idle(row['beforeState'])
            row['idleForInstall']=True
        if a.mode=='install':
            remote='/data/local/tmp/campus-s1-main-'+a.label+'.apk'
            uploaded=False;install_finished=False
            try:
                uploaded=True;push(a.serial,apk,remote)
                row['immediateBeforeInstallState']=snapshot('immediate-before-install')
                require_idle(row['immediateBeforeInstallState'])
                try:
                    data=run('install-r','pm install -r '+shlex.quote(remote),a.timeout)
                    install_finished=True
                    ensure(data=='Success','Package installer did not report success; no fallback/retry')
                except (TimeoutError,OSError,EOFError,RuntimeError) as error:
                    row.update(installOutcome='UNKNOWN',uploadCleanupStatus='BLOCKED')
                    raise Blocked('Install timed out; check the phone installer manually before any retry') from error
                row['installOutcome']='SUCCESS'
            finally:
                # Never race cleanup with an installer whose completion is unknown.
                if uploaded and (install_finished or row.get('installOutcome')!='UNKNOWN'):
                    try:run('remove-upload','rm -f '+shlex.quote(remote));row['uploadCleanupStatus']='PASS'
                    except Exception:row['uploadCleanupStatus']='FAIL'
        after=before if a.mode=='preflight' else installed();row['installed']=after
        if a.mode!='preflight':ensure(after['versionCode']==a.version and after['apkSha256']==a.sha256.upper(),'Installed APK differs from explicit target')
        if a.mode=='snapshot':row['snapshot']=snapshot('snapshot')
        row['status']='PASS'
        if row.get('uploadCleanupStatus')=='FAIL':row['status']='FAIL'
    except Blocked as error:row.update(status='BLOCKED',reason=str(error))
    except Exception as error:
        row.update(status='FAIL',exceptionType=type(error).__name__)
        if isinstance(error,ValueError):row['reason']=str(error)
    finally:
        row['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (out/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:row.get(k) for k in ('status','reason','exceptionType','deviceAlias','installed','snapshot')},ensure_ascii=False))
    return 0 if row['status']=='PASS' else 2 if row['status']=='BLOCKED' else 1
if __name__=='__main__':raise SystemExit(main())
