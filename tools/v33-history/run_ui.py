from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
import argparse,json,hashlib,datetime,time,shlex,sys
from adb_client import shell
r=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--apk',required=True);p.add_argument('--label',required=True);p.add_argument('--font',default='1.0',choices=['1.0','1.3','2.0']);p.add_argument('--nav',default='current',choices=['current','gesture','three']);p.add_argument('--cutout',action='store_true');a=p.parse_args()
assert a.label.replace('-','').isalnum()
out=r/'evidence'/a.label;out.mkdir(exist_ok=True)
row={'testId':'S1-UI','serial':a.serial,'apkSha256':hashlib.sha256(Path(a.apk).read_bytes()).hexdigest().upper(),'fontRequested':a.font,'navigationRequested':a.nav,'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commands':[]}
def run(cmd,timeout=40):
    code,b,e=shell(a.serial,cmd,timeout);row['commands'].append({'command':cmd,'exitCode':code});return code,b,e
oldfont='';oldnav='';changed=False;fontChanged=False;cutoutChanged=False;oldcutout='';oldHardKeyboard=None
try:
    code,b,e=run('pm path org.esurfing.hunan.isolation');assert code==0
    code,b,e=run('sha256sum '+shlex.quote(b.decode().strip().removeprefix('package:')));assert code==0 and b.decode().split()[0].upper()==row['apkSha256']
    _,b,_=run('getprop ro.build.version.sdk');api=int(b);row['api']=api
    if a.serial.startswith('emulator-'):
        code,b,e=run('settings get secure show_ime_with_hard_keyboard');assert code==0
        oldHardKeyboard=b.decode().strip();row['originalShowImeWithHardwareKeyboard']=oldHardKeyboard
        code,_,_=run('settings put secure show_ime_with_hard_keyboard 1');assert code==0
    _,b,_=run('settings get system font_scale');oldfont=b.decode().strip();row['originalFontScale']=oldfont
    _,b,_=run('cmd overlay list --user current');overlays=b.decode().splitlines();oldnav=next((s.split()[-1] for s in overlays if s.startswith('[x]') and 'systemui.navbar.' in s),'');row['originalNavOverlay']=oldnav
    oldcutout=next((s.split()[-1] for s in overlays if s.startswith('[x]') and 'cutout.emulation.' in s),'')
    if a.cutout:
        cutout='com.android.internal.display.cutout.emulation.tall'
        assert any(cutout==s.split()[-1] for s in overlays if s.split()),'Cutout overlay unavailable'
        code,_,_=run('cmd overlay enable-exclusive --user current --category '+cutout);assert code==0;cutoutChanged=True
        row['cutoutOverlay']=cutout
    nav={'gesture':'com.android.internal.systemui.navbar.gestural','three':'com.android.internal.systemui.navbar.threebutton'}.get(a.nav)
    if nav:
        assert any(nav==s.split()[-1] for s in overlays if s.split()),'Requested navigation overlay not installed'
        code,_,_=run('cmd overlay enable-exclusive --user current --category '+nav);assert code==0;changed=True
    if oldfont != a.font:
        code,b,e=run('settings put system font_scale '+a.font)
        assert code==0, 'Device refused font_scale change'
        fontChanged=True
    if api>=33:
        code,_,_=run('pm grant org.esurfing.hunan.isolation android.permission.POST_NOTIFICATIONS');row['notificationGrantExit']=code
    time.sleep(1)
    if a.cutout:
        code,b,e=run("dumpsys display | grep -o 'cutout DisplayCutout{insets=Rect([^)]*)'")
        assert code==0 and b.strip(),'No actual cutout reported'
        row['actualCutoutInsets']=b.decode().strip()
        assert 'Rect(0, 0 - 0, 0)' not in row['actualCutoutInsets'],'Cutout overlay did not take effect'
    run('am force-stop org.esurfing.hunan.isolation')
    code,b,e=run('am instrument -w -r org.esurfing.hunan.isolation/org.esurfing.hunan.UiProbe',100)
    (out/'instrumentation.txt').write_bytes(b)
    assert code==0 and b'INSTRUMENTATION_CODE: -1' in b and b'FAIL' not in b and b'Process crashed' not in b,'Instrumentation did not complete successfully'
    code,b,e=run('run-as org.esurfing.hunan.isolation cat files/ui-result.json');assert code==0
    result=json.loads(b);row['result']=result;row['status']=result['status']
    if result['status']=='PASS':
        assert abs(result['fontScale']-float(a.font))<0.01,'Requested font scale was not applied'
        if api>=30:
            assert any(s['name']=='keyboard' and s.get('imeVisible') for s in result['screens']),'Keyboard was not visible'
    for screen in result.get('screens',[]):
        name=screen['name'];assert name in ['page0','page1','page2','page3','page0-bottom','page1-bottom','page2-bottom','page3-bottom','keyboard']
        code,b,e=run('run-as org.esurfing.hunan.isolation cat files/ui-'+name+'.png');assert code==0
        (out/(name+'.png')).write_bytes(b)
except Exception as e:row.update(status='FAIL',exception=type(e).__name__,reason=str(e))
finally:
    if oldHardKeyboard is not None:
        code,_,_=run('settings delete secure show_ime_with_hard_keyboard' if oldHardKeyboard=='null' else 'settings put secure show_ime_with_hard_keyboard '+oldHardKeyboard)
        row['restoreImeSettingExit']=code
    if cutoutChanged:
        code,_,_=run(('cmd overlay enable-exclusive --user current --category '+oldcutout) if oldcutout else ('cmd overlay disable --user current '+cutout));row['restoreCutoutExit']=code
    if fontChanged:
        code,_,_=run('settings delete system font_scale' if oldfont=='null' else 'settings put system font_scale '+oldfont);row['restoreFontExit']=code
    if changed and oldnav:
        code,_,_=run('cmd overlay enable-exclusive --user current --category '+oldnav);row['restoreNavExit']=code
    cleanupCode,_,_=run('am force-stop org.esurfing.hunan.isolation')
    if cleanupCode!=0 or any(row.get(key,0)!=0 for key in ['restoreCutoutExit','restoreFontExit','restoreNavExit','restoreImeSettingExit']):row['status']='FAIL'
    (out/'result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'label':a.label,'status':row.get('status'),'reason':row.get('reason'),'result':row.get('result'),'restoreFont':row.get('restoreFontExit'),'restoreNav':row.get('restoreNavExit')},ensure_ascii=False),flush=True)
sys.exit(0 if row.get('status')=='PASS' else 1)
