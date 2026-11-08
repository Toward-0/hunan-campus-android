"""Bound, isolated UI checks. No installation, production endpoints or raw device logs."""
from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import sys
import time
from adb_client import devices, shell, query_page_size, PageSizeUnavailable

ROOT = Path(__file__).resolve().parent
PACKAGE = 'org.esurfing.hunan.isolation'
NAV_PREFIX = 'com.android.internal.systemui.navbar.'
CUTOUT_PREFIX = 'com.android.internal.display.cutout.emulation.'
SCREEN_NAMES = {f'page{i}{suffix}' for i in range(4) for suffix in ('', '-bottom')} | {
    'keyboard', 'keyboard-password', 'advanced-first', 'advanced-last', 'advanced-first-keyboard', 'advanced-last-keyboard', 'dropdown'}
p = argparse.ArgumentParser()
for name in ('serial', 'package', 'apk', 'sha256', 'source-id', 'label', 'abi'):
    p.add_argument('--' + name, required=True)
p.add_argument('--version-code', type=int, required=True)
p.add_argument('--api', type=int, required=True)
p.add_argument('--font', choices=('1.0', '2.0'), required=True)
p.add_argument('--nav', choices=('current', 'gesture', 'three'), default='current')
p.add_argument('--cutout', choices=('current', 'none', 'tall'), default='current')
a = p.parse_args()
if a.package != PACKAGE or not re.fullmatch(r'[A-Za-z0-9_-]+', a.label):
    p.error('Explicit isolation package and a simple unique label are required')
if not re.fullmatch(r'[a-fA-F0-9]{64}', a.sha256) or a.version_code <= 33:
    p.error('New revision APK SHA256 and versionCode > 33 are required')
out = ROOT / 'evidence' / a.label
out.mkdir(parents=True, exist_ok=False)
row = {'testId': 'S1-UI', 'sourceId': a.source_id, 'apkSha256': a.sha256.upper(),
       'versionCode': a.version_code, 'package': PACKAGE, 'deviceAlias': 'explicit-selected-device',
       'fontRequested': a.font, 'navigationRequested': a.nav, 'cutoutRequested': a.cutout,
       'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'commands': [], 'restoration': []}
undo = []
bound = False
initial_overlays = None

class Blocked(RuntimeError):
    pass

def run(key, command, timeout=30, required=True):
    code, data, _ = shell(a.serial, command, timeout)
    row['commands'].append({'id': key, 'exitCode': code})
    if required and code != 0:
        raise RuntimeError(key + ' returned nonzero exit code')
    return code, data.decode('utf-8', errors='strict').strip()

def setting(namespace, key, value):
    old = row['original-' + key]
    if old != value:
        restore = f'settings delete {namespace} {key}' if old == 'null' else f'settings put {namespace} {key} {old}'
        undo.append(('restore-' + key, restore))
        run('set-' + key, f'settings put {namespace} {key} {value}')

def overlay_state():
    code, text = run('read-overlays', 'cmd overlay list --user current', required=False)
    if code != 0:
        return None
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r'\s*\[([x ])\]\s+(com\.android\.internal\.(?:systemui\.navbar|display\.cutout\.emulation)\.[A-Za-z0-9_.]+)\s*', line)
        if match:
            result[match[2]] = match[1] == 'x'
    return result

def select_overlay(target, prefix, state):
    if target not in state:
        raise Blocked('Requested overlay is not installed: ' + target)
    active = [name for name, enabled in state.items() if enabled and name.startswith(prefix)]
    if active == [target]:
        return
    if len(active) > 1:
        raise Blocked('Ambiguous initial overlay category')
    restore = ('cmd overlay enable-exclusive --user current --category ' + active[0]) if active else ('cmd overlay disable --user current ' + target)
    undo.append(('restore-' + prefix, restore))
    run('enable-' + target, 'cmd overlay enable-exclusive --user current --category ' + target)

def keep_fields(obj, keys):
    return {key: obj[key] for key in keys if key in obj}

try:
    if (ROOT / 'STOP_UI_MATRIX').exists():
        raise Blocked('UI automation paused by current-stage STOP_UI_MATRIX before device actions')
    apk = Path(a.apk).resolve(strict=True)
    allowed_output = ROOT.parent.parent / 'outputs' / ROOT.name
    if not (apk.is_relative_to(ROOT) or apk.is_relative_to(allowed_output)):
        raise RuntimeError('New revision APK must be within this stage or its matching outputs')
    if hashlib.sha256(apk.read_bytes()).hexdigest().upper() != row['apkSha256']:
        raise RuntimeError('Local APK hash mismatch')
    connected = [line.split() for line in devices().splitlines() if line.split() and line.split()[0] == a.serial]
    if len(connected) != 1 or len(connected[0]) < 2 or connected[0][1] != 'device':
        raise Blocked('Explicit device is missing, offline or unauthorized')
    for key, prop in [('api', 'ro.build.version.sdk'), ('model', 'ro.product.model'),
                      ('abis', 'ro.product.cpu.abilist'), ('qemu', 'ro.kernel.qemu')]:
        _, value = run('property-' + key, 'getprop ' + prop)
        row[key] = value
    if int(row['api']) != a.api or a.abi not in row['abis'].split(','):
        raise RuntimeError('Device API or ABI differs from requested environment')
    page = query_page_size(a.serial)
    row['pageSize'] = page['pageSize']; row['pageSizeEvidence'] = page
    _, package_path = run('package-path', 'pm path ' + PACKAGE)
    paths = package_path.splitlines()
    if len(paths) != 1 or not paths[0].startswith('package:/data/app/'):
        raise RuntimeError('Expected one installed base APK')
    _, digest = run('installed-hash', 'sha256sum ' + shlex.quote(paths[0][8:]))
    if digest.split()[0].upper() != row['apkSha256']:
        raise RuntimeError('Installed APK hash mismatch')
    _, metadata = run('installed-version-abi', f"dumpsys package {PACKAGE} | grep -E 'versionCode=|versionName=|primaryCpuAbi=' ")
    match = re.search(r'\bversionCode=(\d+)\b', metadata)
    native = re.search(r'\bprimaryCpuAbi=([^\s]+)', metadata)
    if not match or int(match[1]) != a.version_code or not native or native[1] != a.abi:
        raise RuntimeError('Installed versionCode or selected native ABI differs')
    row['installedPrimaryAbi'] = native[1]
    bound = True
    overlays = overlay_state()
    initial_overlays = overlays
    if overlays is None and (a.nav != 'current' or a.cutout not in ('current', 'none')):
        raise Blocked('Overlay command unavailable on this API; requested combination cannot be realized')
    # Save the entire recovery baseline before the first system-setting mutation.
    # The explicit serial is intentionally not written; emergency recovery must
    # supply and recheck it against this environment and the installed APK.
    for namespace, key in [('system', 'font_scale'), ('secure', 'show_ime_with_hard_keyboard')]:
        _, old = run('read-' + key, f'settings get {namespace} {key}')
        if not re.fullmatch(r'null|[0-9.]+', old):
            raise RuntimeError('Unexpected original setting ' + key)
        row['original-' + key] = old
    notification_granted = None
    if a.api >= 33:
        _, permission = run('notification-before', f"dumpsys package {PACKAGE} | grep 'android.permission.POST_NOTIFICATIONS: granted=' ")
        match = re.search(r'granted=(true|false)', permission)
        if not match:
            raise RuntimeError('Cannot establish original isolated notification permission')
        notification_granted = match[1] == 'true'
        row['originalNotificationGranted'] = notification_granted
    journal = {'schemaVersion': 1, 'stageId': ROOT.name, 'package': PACKAGE,
        'deviceAlias': row['deviceAlias'], 'apkSha256': row['apkSha256'], 'versionCode': a.version_code,
        'api': int(row['api']), 'model': row['model'], 'pageSize': row['pageSize'],
        'supportedAbis': row['abis'].split(','), 'installedPrimaryAbi': row['installedPrimaryAbi'],
        'capturedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'original': {'font_scale': row['original-font_scale'],
                     'show_ime_with_hard_keyboard': row['original-show_ime_with_hard_keyboard'],
                     'overlays': initial_overlays, 'notificationGranted': notification_granted}}
    pending = out / 'restore-journal.json.pending'
    with pending.open('w', encoding='utf-8') as stream:
        json.dump(journal, stream, ensure_ascii=False, indent=2); stream.flush(); os.fsync(stream.fileno())
    pending.replace(out / 'restore-journal.json')
    if a.nav != 'current':
        if a.api < 29 and a.nav == 'gesture':
            raise Blocked('Framework gesture navigation is unavailable on this old-system matrix entry')
        select_overlay(NAV_PREFIX + {'gesture': 'gestural', 'three': 'threebutton'}[a.nav], NAV_PREFIX, overlays or {})
    if a.cutout == 'tall':
        select_overlay(CUTOUT_PREFIX + 'tall', CUTOUT_PREFIX, overlays or {})
    elif a.cutout == 'none' and overlays is not None:
        for name, enabled in overlays.items():
            if enabled and name.startswith(CUTOUT_PREFIX):
                undo.append(('restore-' + name, 'cmd overlay enable --user current ' + name))
                run('disable-' + name, 'cmd overlay disable --user current ' + name)
    if row['qemu'] == '1':
        setting('secure', 'show_ime_with_hard_keyboard', '1')
    setting('system', 'font_scale', a.font)
    if a.api >= 33:
        if not notification_granted:
            undo.append(('restore-notification', f'pm revoke {PACKAGE} android.permission.POST_NOTIFICATIONS'))
            run('grant-notification', f'pm grant {PACKAGE} android.permission.POST_NOTIFICATIONS')
    time.sleep(1)
    actual_overlays = overlay_state()
    row['actualOverlays'] = [name for name, enabled in (actual_overlays or {}).items() if enabled]
    if a.nav != 'current':
        desired = NAV_PREFIX + {'gesture': 'gestural', 'three': 'threebutton'}[a.nav]
        if desired not in row['actualOverlays']:
            raise Blocked('Navigation overlay did not take effect')
        code, mode = run('navigation-resource', 'cmd overlay lookup android android:integer/config_navBarInteractionMode', required=False)
        number = re.search(r'(?:0x[0-9a-fA-F]+|\d+)\s*$', mode)
        expected = 2 if a.nav == 'gesture' else 0
        if code != 0 or not number or int(number[0], 0) != expected:
            raise Blocked('Actual framework navigation mode could not be verified')
        row['actualNavigationMode'] = expected
    else:
        row['navigationVerification'] = 'current-setting; screenshot review required'
    run('stop-isolation-before', 'am force-stop ' + PACKAGE)
    run('remove-stale-result', 'run-as ' + PACKAGE + ' rm -f files/ui-result.json')
    code, instrument = run('ui-instrumentation', 'am instrument -w -r ' + PACKAGE + '/org.esurfing.hunan.UiProbe', 240, required=False)
    row['instrumentationExitSuccess'] = code == 0 and 'INSTRUMENTATION_CODE: -1' in instrument
    _, data = run('read-ui-result', 'run-as ' + PACKAGE + ' cat files/ui-result.json')
    raw = json.loads(data)
    result = keep_fields(raw, ('testId', 'api', 'model', 'fontScale', 'status', 'failedStep', 'exception', 'reason', 'line',
                              'sessionServicesCreated', 'businessClicks', 'fullVisualAcceptance', 'systemBarVisualReviewRequired'))
    if isinstance(raw.get('popupDebug'), dict):
        result['popupDebug'] = {'adapterClass': raw['popupDebug'].get('adapterClass'),
            'createdRows': [keep_fields(x, ('class','label','width','height','attached','shown')) for x in raw['popupDebug'].get('createdRows', [])],
            'actualRows': [{**keep_fields(x, ('class','label','width','height','measuredWidth','measuredHeight','maxWidth','maxLines','textSize',
                'horizontallyScrollable','transformationClass','parentClass','parentWidth','layoutParamWidth','layoutParamHeight',
                'attached','shown','layoutWidth','lineCount')), 'lines': [keep_fields(line, ('left','right','bottom','ellipsis')) for line in x.get('lines', [])]}
                for x in raw['popupDebug'].get('actualRows', [])]}
        result['popupDebug']['actualCandidates'] = [{**keep_fields(x, ('class','label','width','height','measuredWidth','measuredHeight','maxWidth','maxLines','textSize',
            'horizontallyScrollable','transformationClass','parentClass','parentWidth','layoutParamWidth','layoutParamHeight',
            'attached','shown','layoutWidth','lineCount')), 'lines': [keep_fields(line, ('left','right','bottom','ellipsis')) for line in x.get('lines', [])]}
            for x in raw['popupDebug'].get('actualCandidates', [])]
        result['popupDebug'].update(keep_fields(raw['popupDebug'], ('substep','originatingWindowId','windowId','packageMatches')))
        result['popupDebug']['options'] = [{**keep_fields(x, ('label','matchCount','visibleCount')),
            'nodes':[keep_fields(n, ('visible','bounds','insideSafeBounds')) for n in x.get('nodes',[])]} for x in raw['popupDebug'].get('options',[])]
    result['independentFailures'] = [keep_fields(x, ('testId','status','reason','substep')) for x in raw.get('independentFailures', [])]
    result['screens'] = []
    result['controls'] = [keep_fields(c, ('label', 'bounds', 'safeBounds', 'fullyVisible', 'textFits', 'enabled', 'clickable',
                                             'pageIndex', 'interaction', 'businessClickInvoked', 'selectedIndexBefore', 'selectedIndexAfter', 'textLayoutStatus', 'manualVisualRequired')) for c in raw.get('controls', [])]
    for screen in raw.get('screens', []):
        name = screen['name']
        if name not in SCREEN_NAMES | {'dropdown-failure'} or screen.get('screenshot') != 'ui-' + name + '.png':
            raise RuntimeError('Unrecognized screenshot filename')
        selected = 1 if name.startswith(('dropdown','keyboard', 'advanced')) else int(name[4])
        if screen.get('pageIndex') != selected or screen.get('pageTitle') != ['连接', '账号', '诊断', '更多'][selected]:
            raise RuntimeError('Screenshot page identity mismatch')
        if screen.get('foregroundPackage') != PACKAGE:
            raise RuntimeError('Screenshot was not captured in isolated foreground')
        if name == 'dropdown':
            if screen.get('captureKind') != 'channel-dropdown' or [x.get('label') for x in screen.get('popupOptions', [])] != ['iOS 兼容通道 · 优先验证', '旧 Windows 通道 · 未通过放行验收']:
                raise RuntimeError('Dropdown identity or original option text mismatch')
            if not screen.get('adapterUnchanged') or not screen.get('manualVisualRequired') or screen.get('textLayoutStatus') != 'NOT_RUN':
                raise RuntimeError('Dropdown must preserve the original adapter and require visual text review')
            if not all(x.get('fullyVisible') and x.get('manualVisualRequired') and x.get('textLayoutStatus') == 'NOT_RUN' and 'textFits' not in x for x in screen['popupOptions']):
                raise RuntimeError('Dropdown visibility evidence or manual text-layout boundary is invalid')
        scode, image, _ = shell(a.serial, 'run-as ' + PACKAGE + ' cat files/' + shlex.quote(screen['screenshot']), 30)
        if scode != 0 or hashlib.sha256(image).hexdigest() != screen['sha256']:
            raise RuntimeError('Screenshot hash mismatch')
        (out / (name + '.png')).write_bytes(image)
        result['screens'].append(keep_fields(screen, ('name', 'pageIndex', 'pageTitle', 'contentMarker', 'activity', 'activityInstance',
            'foregroundPackage', 'windowId', 'safeBounds', 'screenshot', 'sha256', 'displayBounds', 'imeVisible', 'systemInsets', 'cutoutInsets', 'imeInsets', 'captureKind', 'textLayoutStatus', 'manualVisualRequired', 'adapterUnchanged')))
        if name == 'dropdown':
            result['screens'][-1]['popupOptions'] = [keep_fields(x, ('label', 'bounds', 'safeBounds', 'fullyVisible', 'textLayoutStatus', 'manualVisualRequired')) for x in screen['popupOptions']]
    row['result'] = result
    if raw.get('status') != 'PASS' or not row['instrumentationExitSuccess']:
        raise RuntimeError('UI probe failed: ' + str(raw.get('failedStep', 'instrumentation')))
    if abs(float(raw['fontScale']) - float(a.font)) >= .01:
        raise RuntimeError('Requested font scale did not take effect')
    if {screen['name'] for screen in result['screens']} != SCREEN_NAMES:
        raise RuntimeError('Required screenshot set is incomplete')
    if a.api >= 30:
        keyboard = [s for s in result['screens'] if s['name'].startswith('keyboard') or s['name'].endswith('-keyboard')]
        if len(keyboard) != 4 or not all(s.get('imeVisible') for s in keyboard):
            raise RuntimeError('Account or advanced-field keyboard evidence is missing')
        if a.cutout == 'tall' and not any(re.search(r'top=[1-9][0-9]*', s.get('cutoutInsets', '')) for s in result['screens']):
            raise Blocked('Tall cutout has no actual WindowInsets evidence')
        if a.cutout == 'none' and any(re.search(r'(?:left|top|right|bottom)=[1-9][0-9]*', s.get('cutoutInsets', '')) for s in result['screens']):
            raise Blocked('Display still has actual cutout insets in requested no-cutout case')
    row['status'] = 'PASS'
except PageSizeUnavailable as error:
    row.update(status='BLOCKED', reason=str(error), pageSizeAttempts=error.attempts)
except Blocked as error:
    row.update(status='BLOCKED', reason=str(error))
except Exception as error:
    row.update(status='FAIL', exception=type(error).__name__, reason=str(error))
finally:
    if bound:
        try:
            run('stop-isolation-after', 'am force-stop ' + PACKAGE)
        except Exception:
            row.update(status='FAIL', cleanupFailure=True)
    for key, command in reversed(undo):
        try:
            code, _ = run(key, command, required=False)
            row['restoration'].append({'id': key, 'status': 'PASS' if code == 0 else 'FAIL'})
            if code != 0:
                row['status'] = 'FAIL'
        except Exception:
            row['restoration'].append({'id': key, 'status': 'FAIL'}); row['status'] = 'FAIL'
    if bound:
        # Exit zero alone does not prove settings have returned to the original value.
        try:
            for namespace, key in [('system', 'font_scale'), ('secure', 'show_ime_with_hard_keyboard')]:
                if 'original-' + key in row:
                    _, actual = run('verify-restored-' + key, f'settings get {namespace} {key}')
                    passed = actual == row['original-' + key]
                    row['restoration'].append({'id': 'verify-' + key, 'status': 'PASS' if passed else 'FAIL'})
                    if not passed:
                        row['status'] = 'FAIL'
            if initial_overlays is not None:
                actual = overlay_state()
                passed = actual == initial_overlays
                row['restoration'].append({'id': 'verify-overlays', 'status': 'PASS' if passed else 'FAIL'})
                if not passed:
                    row['status'] = 'FAIL'
            if 'originalNotificationGranted' in row:
                _, value = run('verify-notification-restored', f"dumpsys package {PACKAGE} | grep 'android.permission.POST_NOTIFICATIONS: granted=' ")
                match = re.search(r'granted=(true|false)', value)
                passed = match is not None and (match[1] == 'true') == row['originalNotificationGranted']
                row['restoration'].append({'id': 'verify-notification', 'status': 'PASS' if passed else 'FAIL'})
                if not passed:
                    row['status'] = 'FAIL'
        except Exception:
            row['restoration'].append({'id': 'verify-restored-state', 'status': 'FAIL'}); row['status'] = 'FAIL'
    row['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (out / 'result.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'label': a.label, 'status': row['status'], 'reason': row.get('reason'),
                  'screens': len(row.get('result', {}).get('screens', [])), 'restoration': row['restoration']}, ensure_ascii=False))
sys.exit(0 if row['status'] == 'PASS' else 2 if row['status'] == 'BLOCKED' else 1)
