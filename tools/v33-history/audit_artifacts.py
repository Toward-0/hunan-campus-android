from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
import zipfile,hashlib,struct,json,subprocess,xml.etree.ElementTree as ET,datetime,re
r=Path(__file__).resolve().parent;o=r.parent.parent/'outputs'/r.name
tool=r/'sdk/build-tools/35.0.0/aapt2.exe';readelf=r/'sdk/ndk/28.0.13004108/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe'
report=[]
for apk in o.glob('*.apk'):
    row={'file':apk.name,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest().upper(),'time':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    main='candidate' in apk.name
    meta=subprocess.run([str(tool),'dump','badging',str(apk)],capture_output=True,check=True).stdout.decode(errors='replace')
    (r/'evidence'/(apk.stem+'-metadata.txt')).write_text(meta,encoding='utf-8')
    manifest=subprocess.run([str(tool),'dump','xmltree',str(apk),'--file','AndroidManifest.xml'],capture_output=True,check=True).stdout.decode(errors='replace')
    (r/'evidence'/(apk.stem+'-manifest.txt')).write_text(manifest,encoding='utf-8')
    row['metadata']={key:re.search(pattern,meta).group(1) for key,pattern in {'package':r"package: name='([^']+)'",'versionCode':r"versionCode='([^']+)'",'versionName':r"versionName='([^']+)'",'minSdk':r"minSdkVersion:'([^']+)'",'targetSdk':r"targetSdkVersion:'([^']+)'"}.items()}
    assert row['metadata']=={'package':'org.esurfing.hunan'+('' if main else '.isolation'),'versionCode':'33','versionName':'0.2.21-compat-s1'+('' if main else '-isolation'),'minSdk':'26','targetSdk':'35'}
    row['nativeLibraries']=[]
    with zipfile.ZipFile(apk) as z:
        libs=[n for n in z.namelist() if n.startswith('lib/') and n.endswith('.so')]
        for n in libs:
            b=z.read(n);bits=64 if b[4]==2 else 32
            off=struct.unpack_from('<Q' if bits==64 else '<I',b,32 if bits==64 else 28)[0]
            entsize,count=struct.unpack_from('<HH',b,54 if bits==64 else 42)
            loads=[]
            for i in range(count):
                pos=off+i*entsize
                if struct.unpack_from('<I',b,pos)[0]==1:
                    if bits==64:fo,va=struct.unpack_from('<QQ',b,pos+8);align=struct.unpack_from('<Q',b,pos+48)[0]
                    else:fo,va=struct.unpack_from('<II',b,pos+4);align=struct.unpack_from('<I',b,pos+28)[0]
                    loads.append({'fileOffset':fo,'virtualAddress':va,'alignment':align,'aligned16k':align>=16384 and (va-fo)%16384==0})
            native={'entry':n,'bits':bits,'sha256':hashlib.sha256(b).hexdigest().upper(),'loadSegments':loads,'16kApplicable':bits==64,'status':'PASS' if bits==32 or all(x['aligned16k'] for x in loads) else 'FAIL'}
            dest=r/'pack'/apk.stem/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
            p=subprocess.run([str(readelf),'-lW',str(dest)],capture_output=True,check=True)
            (r/'evidence'/(apk.stem+'-'+n.split('/')[1]+'-elf.txt')).write_bytes(p.stdout)
            if main:
                assert b'Java_org_esurfing_hunan_CompatProbe' not in b
                assert b'isolation_fail_allocation' not in b
            row['nativeLibraries'].append(native)
        if main:
            assert {n.split('/')[1] for n in libs}=={'arm64-v8a','armeabi-v7a'}
            assert not any('synthetic' in n for n in z.namelist())
            dex=b''.join(z.read(n) for n in z.namelist() if n.endswith('.dex'))
            for name in ['RepairMenuProbe','DiscoveryProbe','CompatProbe','UiProbe','NativeSmoke','ProtocolProbe','DebugControlReceiver','StabilityProbe','StabilityFixture','MockSessionService']:
                assert ('Lorg/esurfing/hunan/'+name+';').encode() not in dex
            assert 'E: instrumentation' not in manifest
            row['testEntrypointsAbsent']=True
    row['status']='PASS' if all(x['status']=='PASS' for x in row['nativeLibraries']) else 'FAIL';report.append(row)
(r/'evidence/apk-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
for x in report:print(x['file'],x['status'],x['sha256'])
