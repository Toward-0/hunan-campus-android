"""Static APK audit only; does not install, build, or claim device compatibility."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write, OUTPUT
import argparse, collections, datetime, hashlib, json, os, re, struct, subprocess
import xml.etree.ElementTree as ET
import zipfile

CERT = '2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229'
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()
def ensure(condition, message):
    if not condition: raise ValueError(message)
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()

def dex_classes(data):
    ensure(data[:4] == b'dex\n' and len(data) >= 112, 'Invalid DEX header')
    string_count, string_offset = struct.unpack_from('<II', data, 56)
    type_count, type_offset = struct.unpack_from('<II', data, 64)
    class_count, class_offset = struct.unpack_from('<II', data, 96)
    ensure(string_offset+string_count*4 <= len(data) and type_offset+type_count*4 <= len(data)
           and class_offset+class_count*32 <= len(data), 'DEX tables outside file')
    result = set()
    for i in range(class_count):
        type_index = struct.unpack_from('<I', data, class_offset+i*32)[0]
        ensure(type_index < type_count, 'DEX class type outside table')
        string_index = struct.unpack_from('<I', data, type_offset+type_index*4)[0]
        ensure(string_index < string_count, 'DEX descriptor outside table')
        pos = struct.unpack_from('<I', data, string_offset+string_index*4)[0]
        for _ in range(5):
            ensure(pos < len(data), 'Invalid DEX string')
            part = data[pos]; pos += 1
            if not part & 128: break
        else: raise ValueError('Invalid DEX string length')
        end = data.index(0, pos)
        result.add(data[pos:end].decode('utf-8', errors='replace'))
    return result

def elf_info(data, abi):
    ensure(data[:4] == b'\x7fELF' and data[4] in (1,2) and data[5] == 1, 'Unsupported ELF header')
    bits = 64 if data[4] == 2 else 32
    machine = struct.unpack_from('<H', data, 18)[0]
    ensure((bits,machine) == {'arm64-v8a':(64,183),'armeabi-v7a':(32,40),'x86_64':(64,62)}[abi], 'ELF ABI mismatch')
    offset = struct.unpack_from('<Q' if bits == 64 else '<I', data, 32 if bits == 64 else 28)[0]
    entry_size, count = struct.unpack_from('<HH', data, 54 if bits == 64 else 42)
    ensure(entry_size >= (56 if bits == 64 else 32) and offset+entry_size*count <= len(data), 'Invalid ELF program headers')
    loads = []
    for i in range(count):
        pos = offset+i*entry_size
        if struct.unpack_from('<I', data, pos)[0] != 1: continue
        if bits == 64:
            file_offset, virtual = struct.unpack_from('<QQ', data, pos+8)
            alignment = struct.unpack_from('<Q', data, pos+48)[0]
        else:
            file_offset, virtual = struct.unpack_from('<II', data, pos+4)
            alignment = struct.unpack_from('<I', data, pos+28)[0]
        loads.append({'fileOffset':file_offset,'virtualAddress':virtual,'alignment':alignment,
                      'aligned16k':alignment >= 16384 and (virtual-file_offset)%16384 == 0})
    ensure(loads, 'No ELF LOAD segments')
    ensure(bits != 64 or all(x['aligned16k'] for x in loads), '64-bit ELF LOAD is not 16KB aligned')
    return {'bits':bits,'machine':machine,'loadSegments':loads,'elf16kApplicable':bits == 64,
            'elf16kStatus':'PASS' if bits == 64 else 'NOT_RUN','status':'PASS'}

def main():
    stage = require_mutable_stage()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',required=True)
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--label',required=True)
    args = parser.parse_args()
    ensure(re.fullmatch(r'[A-Za-z0-9._-]+',args.source_id), 'Invalid source identifier')
    ensure(re.fullmatch(r'[A-Za-z0-9-]+',args.label), 'Invalid audit label')
    evidence = assert_stage_write(stage/'evidence'/args.label)
    ensure(not evidence.exists(), 'Keep earlier audit evidence; use a new label')
    evidence.mkdir()
    source = stage/'source'
    tools = json.loads((stage/'tools.local.json').read_text(encoding='utf-8-sig'))
    ensure(Path(os.environ.get('JAVA_HOME','')).resolve() == Path(tools['JdkHome']).resolve(),
           'Initialize source/stage-env.ps1 before audit')
    sdk = Path(tools['AndroidSdk'])
    aapt = sdk/'build-tools/35.0.0/aapt2.exe'
    align = sdk/'build-tools/35.0.0/zipalign.exe'
    llvm = sdk/'ndk/28.0.13004108/toolchains/llvm/prebuilt/windows-x86_64/bin'
    java = Path(tools['JdkHome'])/'bin/java.exe'
    report = {'testId':'STATIC-APK-AUDIT','time':now(),'sourceId':args.source_id,
              'scope':'Static APK checks only. Build provenance uses separate build records; no device or stage-wide PASS is implied.',
              'status':'FAIL','apks':[],'lint':[]}
    commands = []
    def command(argv, label):
        record = {'id':label,'arguments':[str(x) for x in argv],'startedAt':now()}
        commands.append(record)
        try:
            completed = subprocess.run([str(x) for x in argv],capture_output=True,timeout=60)
            record['exitCode'] = completed.returncode
            ensure(completed.returncode == 0, 'Static audit tool failed: '+label)
            return completed.stdout.decode(errors='replace')
        except subprocess.TimeoutExpired:
            record.update(status='FAIL',reason='timeout')
            raise
    try:
        manifest_path = Path(args.source_manifest).resolve()
        ensure(manifest_path.is_relative_to(stage) or manifest_path.is_relative_to(OUTPUT),
               'Use a manifest from this revision')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        entries = manifest if isinstance(manifest,list) else manifest.get('files',[])
        ensure(entries, 'Source manifest is empty')
        for entry in entries:
            relative = Path(entry['path'])
            path = (source/relative).resolve()
            ensure(not relative.is_absolute() and path.is_relative_to(source.resolve()), 'Invalid source manifest path')
            ensure(path.is_file() and sha(path) == entry['sha256'].upper(), 'Source manifest differs from actual input')
        report.update(sourceManifestSha256=sha(manifest_path),sourceManifestFiles=len(entries),currentSourceManifestStatus='PASS')
        gradle = (source/'app/build.gradle.kts').read_text(encoding='utf-8')
        version = re.search(r'versionName\s*=\s*"([^"]+)"',gradle).group(1)
        code = int(re.search(r'versionCode\s*=\s*(\d+)',gradle).group(1))
        ensure(code > 33, 'New code version must exceed 33')
        report.update(versionName=version,versionCode=code)
        def declarations(folder):
            return {name for file in folder.rglob('*.kt')
                    for name in re.findall(r'\b(?:class|object|interface)\s+([A-Za-z_]\w*)',file.read_text(encoding='utf-8'))}
        excluded = declarations(source/'app/src/isolation') - declarations(source/'app/src/main') - declarations(source/'app/src/candidate')
        excluded |= {'DiagnosticsProbe','DiagnosticsRegression','RepairMenuProbe','CompatProbe','UiProbe','StabilityProbe','StabilityFixture','MockSessionService'}
        fixture_assets = {p.relative_to(source/'app/src/isolation/assets').as_posix()
                          for p in (source/'app/src/isolation/assets').rglob('*') if p.is_file()}
        report['checkedIsolationClassNames'] = sorted(excluded)
        definitions = [('candidate','phone',{'arm64-v8a','armeabi-v7a'}),
                       ('isolation','phone',{'arm64-v8a','armeabi-v7a'}),
                       ('isolation','arm32',{'armeabi-v7a'}),('isolation','x86_64',{'x86_64'})]
        for variant, flavor, required_abis in definitions:
            apk = OUTPUT/f'ESurfingHunan-{version}-{variant}-{flavor}.apk'
            row = {'testId':'APK-'+variant+'-'+flavor,'file':apk.name,'sourceId':args.source_id,
                   'sourceManifestSha256':report['sourceManifestSha256'],'time':now(),'status':'NOT_RUN'}
            report['apks'].append(row)
            if not apk.is_file():
                row['reason']='APK missing'; continue
            row.update(sha256=sha(apk),status='FAIL')
            try:
                is_main = variant == 'candidate'
                meta = command([aapt,'dump','badging',apk],apk.stem+'-metadata')
                expected = {'package':'org.esurfing.hunan'+('' if is_main else '.isolation'),
                            'versionCode':str(code),'versionName':version+('' if is_main else '-isolation'),
                            'minSdk':'26','targetSdk':'35'}
                patterns = {'package':r"package: name='([^']+)'",'versionCode':r"versionCode='([^']+)'",
                            'versionName':r"versionName='([^']+)'",'minSdk':r"(?:minSdkVersion|sdkVersion):'([^']+)'",
                            'targetSdk':r"targetSdkVersion:'([^']+)'"}
                row['metadata'] = {k:re.search(patterns[k],meta).group(1) for k in patterns}
                ensure(row['metadata'] == expected, 'APK identity/API mismatch')
                manifest_text = command([aapt,'dump','xmltree',apk,'--file','AndroidManifest.xml'],apk.stem+'-manifest')
                signature = command([java,'-XX:-UsePerfData','-Djava.io.tmpdir='+str(stage/'tmp'),
                    '-Duser.home='+str(stage/'java-user'),'-jar',sdk/'build-tools/35.0.0/lib/apksigner.jar',
                    'verify','--print-certs',apk],apk.stem+'-signature')
                certs = {c.lower() for c in re.findall(r'certificate SHA-256 digest:\s*([a-fA-F0-9]{64})',signature)}
                ensure(certs == {CERT}, 'Unexpected signing certificate')
                row['certificateSha256'] = CERT
                aligned = command([align,'-c','-P','16','-v','4',apk],apk.stem+'-zipalign')
                (evidence/(apk.stem+'-zipalign.txt')).write_text(aligned,encoding='utf-8')
                row['zipalign16kStatus']='PASS'
                natives=[]; classes=set(); native_test_symbol=False
                with zipfile.ZipFile(apk) as archive:
                    names=archive.namelist()
                    libraries=[n for n in names if re.fullmatch(r'lib/[^/]+/[^/]+\.so',n)]
                    ensure({n.split('/')[1] for n in libraries} == required_abis, 'APK ABI set mismatch')
                    for name in names:
                        if re.fullmatch(r'classes(?:\d+)?\.dex',name): classes |= dex_classes(archive.read(name))
                    ensure(classes, 'No DEX class definitions')
                    for name in libraries:
                        data=archive.read(name); abi=name.split('/')[1]
                        native=elf_info(data,abi)
                        native.update(entry=name,sha256=hashlib.sha256(data).hexdigest().upper())
                        destination=assert_stage_write(stage/'pack'/args.label/apk.stem/name)
                        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
                        headers=command([llvm/'llvm-readelf.exe','-lW',destination],apk.stem+'-'+abi+'-elf')
                        (evidence/(apk.stem+'-'+abi+'-elf.txt')).write_text(headers,encoding='utf-8')
                        symbols=command([llvm/'llvm-nm.exe','-D','--defined-only',destination],apk.stem+'-'+abi+'-symbols')
                        has_hook='Java_org_esurfing_hunan_CompatProbe' in symbols or 'isolation_fail_allocation' in symbols
                        native_test_symbol |= has_hook
                        if is_main: ensure(not has_hook, 'Native test hook entered main APK')
                        natives.append(native)
                    if is_main:
                        forbidden=[cls for cls in classes for name in excluded
                                   if cls == 'Lorg/esurfing/hunan/'+name+';' or cls.startswith('Lorg/esurfing/hunan/'+name+'$')]
                        ensure(not forbidden,'Isolation class entered main DEX')
                        ensure('E: instrumentation' not in manifest_text,'Instrumentation entered main manifest')
                        ensure(not any(n == 'assets/'+asset for n in names for asset in fixture_assets),
                               'Isolation fixture asset entered main APK')
                        row['testEntrypointsAbsent']=True
                    else:
                        for probe in ('DiagnosticsProbe','CompatProbe','RepairMenuProbe','UiProbe'):
                            ensure('Lorg/esurfing/hunan/'+probe+';' in classes and probe in manifest_text,'Missing isolated probe')
                        ensure(native_test_symbol,'Isolated native hook missing')
                row.update(nativeLibraries=natives,abis=sorted(required_abis),dexClassCount=len(classes),status='PASS')
            except Exception as error:
                row.update(status='FAIL',exceptionType=type(error).__name__)
                if isinstance(error,ValueError): row['reason']=str(error)
        for variant in ('candidate','isolation'):
            path=source/f'app/build/reports/lint-results-{variant}.xml'
            row={'testId':'LINT-'+variant,'variant':variant,'status':'NOT_RUN'}
            report['lint'].append(row)
            if path.is_file():
                issues=ET.parse(path).getroot().findall('issue')
                counts=collections.Counter(issue.get('severity','Unknown') for issue in issues)
                errors=counts['Error']+counts['Fatal'];warnings=counts['Warning']
                row.update(reportSha256=sha(path),errors=errors,warnings=warnings,severities=dict(counts),
                           ruleCounts=dict(collections.Counter(issue.get('id','Unknown') for issue in issues)),
                           status='PASS' if errors==0 else 'FAIL',zeroWarningTarget='PASS' if warnings==0 else 'FAIL')
        report['status']='PASS' if all(x['status']=='PASS' for x in report['apks']+report['lint']) else 'FAIL'
    except Exception as error:
        report.update(status='FAIL',exceptionType=type(error).__name__)
        if isinstance(error,ValueError):report['reason']=str(error)
    finally:
        report['finishedAt']=now()
        (evidence/'apk-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (evidence/'audit-commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'evidence':str(evidence/'apk-audit.json'),
                      'apks':[{k:x.get(k) for k in ('file','status','reason')} for x in report['apks']]},ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
