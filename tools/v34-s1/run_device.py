"""Explicit-device isolated probes, fixed-field evidence, bounded cleanup."""
from stage_guard import require_mutable_stage, assert_stage_write
from adb_client import shell,push,devices,query_page_size,PageSizeUnavailable
from pathlib import Path
import argparse,hashlib,json,datetime,re,subprocess,shlex,sys,os
r=require_mutable_stage()
p=argparse.ArgumentParser()
for key in ('serial','package','apk','sha256','source-id','label'):p.add_argument('--'+key,required=True)
p.add_argument('--version',type=int,required=True);p.add_argument('--install',action='store_true')
p.add_argument('--probe',choices=['install-only','CompatProbe','RepairMenuProbe','StabilityProbe','DiscoveryProbe','DiagnosticsProbe','InternetProbe','SessionProbe'],default='CompatProbe')
p.add_argument('--mode',choices=['repair','account','lifecycle','transport','export','session']);p.add_argument('--timeout',type=int,default=240)
p.add_argument('--process-bits',type=int,choices=[32,64]);a=p.parse_args()
assert a.package=='org.esurfing.hunan.isolation', 'Only isolated package is allowed'
assert (a.probe=='DiagnosticsProbe' and a.mode in ('export','session')) or (a.probe!='DiagnosticsProbe' and a.mode not in ('export','session'))
assert re.fullmatch(r'[A-Za-z0-9-]+',a.label)
assert 15<=a.timeout<=900
apk=Path(a.apk).resolve();sha=hashlib.sha256(apk.read_bytes()).hexdigest().upper()
assert sha==a.sha256.upper()
out=assert_stage_write(r/'evidence'/a.label)
assert not out.exists(), 'Keep earlier evidence; use a fresh run label'
out.mkdir()
row={'testId':a.probe,'mode':a.mode,'package':a.package,'apk':apk.name,'apkSha256':sha,'sourceId':a.source_id,'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'expected':'isolated assertions pass; cleanup succeeds','status':'FAIL','commands':[]}
deviceVerified=False
class MatrixPaused(RuntimeError): pass
def run(command,timeout=30):
    code,b,e=shell(a.serial,command,timeout)
    row['commands'].append({'shell':command,'exitCode':code})
    return code,b,e
def property(name):
    code,b,_=run('getprop '+name);assert code==0
    return b.decode().strip()
def read_json_file(name,allowed):
    assert re.fullmatch(r'[a-z0-9-]+\.json',name)
    code,b,_=run('run-as '+a.package+' cat files/'+name);assert code==0
    parsed=json.loads(b)
    # Selection happens before any persistent collection.
    return {k:parsed[k] for k in allowed if k in parsed}
try:
    if (r/'STOP_DEVICE_MATRIX').exists():
        raise MatrixPaused('Batch paused for a reviewed revision fix; no device action was performed')
    tools=json.loads((r/'tools.local.json').read_text(encoding='utf-8-sig'))
    if Path(os.environ.get('JAVA_HOME','')).resolve()!=Path(tools['JdkHome']).resolve():
        raise RuntimeError('Initialize source/stage-env.ps1 before device scripts')
    verify=subprocess.run([str(Path(tools['JdkHome'])/'bin/java.exe'),'-XX:-UsePerfData',
        '-Djava.io.tmpdir='+str(r/'tmp'),'-Duser.home='+str(r/'java-user'),
        '-jar',str(r/'sdk/build-tools/35.0.0/lib/apksigner.jar'),'verify','--print-certs',str(apk)],capture_output=True,timeout=30)
    certs=re.findall(r'certificate SHA-256 digest:\s*([0-9a-fA-F]{64})',verify.stdout.decode(errors='replace'))
    expected_cert='2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229'
    row['signature']={'exitCode':verify.returncode,'certificateSha256':[c.lower() for c in certs]}
    assert verify.returncode==0 and certs and {c.lower() for c in certs}=={expected_cert},'APK signature does not match existing test certificate'
    online={line.split()[0]:line.split()[1] for line in devices().splitlines() if line.strip()}
    assert online.get(a.serial)=='device','Explicit target is not online/authorized'
    model=property('ro.product.model');api=int(property('ro.build.version.sdk'))
    qemu=property('ro.kernel.qemu')
    assert model in ('RMX3820','V2307A') or qemu=='1','Device not in confirmed scope'
    deviceVerified=True
    row.update(deviceAlias=a.serial if qemu=='1' else model,api=api,model=model,supportedAbis=property('ro.product.cpu.abilist').split(','))
    page=query_page_size(a.serial);row['pageSize']=page['pageSize'];row['pageSizeEvidence']=page
    tool=r/'sdk/build-tools/35.0.0/aapt.exe'
    meta=subprocess.run([str(tool),'dump','badging',str(apk)],capture_output=True,timeout=20,check=True).stdout.decode(errors='replace')
    assert re.search(r"package: name='"+re.escape(a.package)+r"' versionCode='"+str(a.version)+r"'",meta)
    apkabis=re.findall(r"'([^']+)'",next(line for line in meta.splitlines() if line.startswith('native-code:')))
    assert set(apkabis)&set(row['supportedAbis'])
    row['versionCode']=a.version;row['apkAbis']=apkabis
    if a.install:
        remote='/data/local/tmp/campus-s1-'+a.label+'.apk'
        push(a.serial,apk,remote)
        try:
            code,b,_=run('pm install -r '+shlex.quote(remote),120)
            row['installSuccess']=code==0 and b'Success' in b
            assert row['installSuccess'],'Install refused/failed; never uninstall or clear production data'
        finally:
            code,_,_=run('rm -f '+shlex.quote(remote));assert code==0
    code,b,_=run('pm path '+a.package);assert code==0
    installed=b.decode().strip().removeprefix('package:')
    assert installed.startswith('/data/app/') and installed.endswith('.apk') and '\n' not in installed
    code,b,_=run('sha256sum '+shlex.quote(installed));assert code==0
    assert b.decode().split()[0].upper()==sha,'Installed APK differs from explicit input'
    row['installedApkSha256']=sha
    if a.probe!='install-only':
        code,_,_=run('am force-stop '+a.package);assert code==0,'Isolated force-stop failed'
        command='am instrument -w -r '+(('-e mode '+a.mode+' ') if a.mode else '')+a.package+'/org.esurfing.hunan.'+a.probe
        code,b,_=run(command,a.timeout)
        # Test IDs such as READ-FAILURE describe expected fault cases, not failed assertions.
        failed=bool(re.search(rb'(?m)^INSTRUMENTATION_(?:FAILED:|RESULT: shortMsg=|RESULT: result=FAIL\b)',b)) or b'Process crashed' in b or bool(re.search(rb'"status"\s*:\s*"FAIL"',b))
        row['instrumentation']={'exitCode':code,'completed':b'INSTRUMENTATION_CODE: -1' in b,'reportedFailure':failed}
        instrumentation_ok=code==0 and row['instrumentation']['completed'] and not row['instrumentation']['reportedFailure']
        if a.probe=='CompatProbe':
            result=read_json_file('compat-jni.json',{'testId','status','api','model','manufacturer','supportedAbis','process64','pageSize','nativeBits','loadedAbi','malformedRejected','cycles','syntheticAlgorithms','allocationFailurePositionsPerAlgorithm','handlesAfter','step','exception','line'})
            assert result['status']=='PASS' and result['handlesAfter']==0
            assert result['nativeBits']==(64 if result['process64'] else 32)
            assert result['pageSize']==row['pageSize'],'JNI sysconf page size differs from pre-install query'
            if a.process_bits:assert result['nativeBits']==a.process_bits
            row['result']=result
        elif a.probe=='RepairMenuProbe':
            result=read_json_file('repair-menu-result.json',{'status','api','model','cases','serviceCommands'})
            assert result['status']=='PASS' and result['serviceCommands']==0;row['result']=result
        elif a.probe=='DiagnosticsProbe':
            result=read_json_file('diagnostics-'+a.mode+'.json',{'testId','mode','status','cases','api','process64','case','exception','line','expected','actual','observedHeartbeatFailure','cleanup','handlesAfter','loginRequests','logoutRequests','historyStartWall','currentRunFailureEvents','minimumCurrentRunFailureEvents'})
            row['result']=result
            assert result['status']=='PASS' and result.get('handlesAfter',0)==0
        elif a.probe=='StabilityProbe':
            code,b,_=run('run-as '+a.package+' cat files/stability-'+(a.mode or 'lifecycle')+'.jsonl');assert code==0
            allowed={'case','elapsed','pid','handles','threadsTotal','threadsWithoutFixture','platformPools','ownedPools','calls','deadlines','callbacks','jniHandlesIncludingFixture','nativeBytes','fd','discoveryRequests','loginRequests','logoutRequests','generation','requests','acceptedSockets','keepRequests'}
            row['cases']=[{k:v for k,v in obj.items() if k in allowed} for obj in (json.loads(line) for line in b.decode().splitlines() if line.strip())]
        assert instrumentation_ok,'Instrumentation assertions failed'
    row['status']='PASS'
except PageSizeUnavailable as ex:
    row.update(status='BLOCKED',reason=str(ex),pageSizeAttempts=ex.attempts)
except MatrixPaused as ex:
    row.update(status='BLOCKED',reason=str(ex))
except Exception as ex:
    row.update(status='FAIL',exceptionType=type(ex).__name__)
    # Assertion messages are fixed script text, never device/server exception payloads.
    if isinstance(ex,AssertionError) and ex.args:row['reason']=str(ex)
finally:
    if deviceVerified:
        try:
            code,_,_=run('am force-stop '+a.package);row['cleanupExit']=code
            if code!=0:row['status']='FAIL'
        except Exception:row.update(status='FAIL',cleanupExit=-1)
    (out/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:row.get(k) for k in ('testId','deviceAlias','status','reason','exceptionType','result','instrumentation')},ensure_ascii=False),flush=True)
sys.exit(0 if row['status']=='PASS' else 2 if row['status']=='BLOCKED' else 1)
