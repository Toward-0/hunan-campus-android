"""Reviewed, explicit-input delivery packaging. Does not build, install, seal, commit, or publish.

Explicit reviewed-input interface:
  python -B package_revision.py --iteration r4 --baseline-source <published-source>
    --build-record evidence/build-phone-... --build-record evidence/build-arm32-...
    --build-record evidence/build-x86_64-... --reviewed-script run_device.py ...
    [--gate-plan <reviewed-json>] [--extra-result evidence/<reviewed-result>.json]
    [--reviewed-screenshot evidence/<selected-current-run>/<image>.png]

A gate plan is a list of {testId, expected, evidenceLabels, required?}. It maps requirements to
specific reviewed results; it cannot set statuses. Empty/missing mappings stay NOT_RUN.
Select final iteration explicitly; an iteration label alone never proves APK identity.
Raw logs, local configuration, serials and signing values are never copied.
"""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write, OUTPUT
import argparse
import collections
import datetime
import difflib
import hashlib
import io
import json
import re
import zipfile

STATES = {'PASS', 'FAIL', 'NOT_RUN', 'BLOCKED'}
PUBLISHED_MANIFEST = 'E5D4794F2CA708136B5CE8687566200A7F3A184D8D9151BB253595E83737918E'
ORIGINAL_MANIFEST = 'C83DFEAB98CBBA964C53000D9C01B300E98F706DBFBD2D376E0DAB6117F77DEA'
CERT = '2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229'
SOURCE_EXCLUDES = ('.gradle/', '.kotlin/', 'app/build/', 'build/')
PRIVATE_SUFFIXES = {'.jks', '.keystore', '.p12', '.pfx', '.pem', '.key'}
# The source archive is separately restricted to the exact verified build manifest.
SCRIPT_CANDIDATES = {
    'stage_guard.py', 'adb_client.py', 'run_device.py', 'run_ui.py', 'main-device.py',
    'restore_revision.py', 'start_emulator.py', 'audit_artifacts.py', 'package_revision.py', 'matrix-suite.py', 'verify-protected.py',
    'run_remaining_matrix.py', 'record_visual_review.py', 'run_realme_batch.py', 'emulator_process_guard.py',
    'DEVICE_AND_RECOVERY.txt',
}
DEFAULT_GATES = {
    'JSON-COMPLETE-RECORDS': '整段复制内容每个非空记录独立解析；完整记录边界及字段白名单通过',
    'DIAGNOSTIC-CURRENT-STATE': '失败后成功清当前协议码；本轮历史错误保留；旧代次不能覆盖新代次',
    'UI-API35-COMPLETE': '约定字体/导航/刘海/键盘组合，四页身份和截图一致；逐图检查及关键控件可达',
    **{f'API{api}-CURRENT-BUILD': f'API{api}本轮构建约定隔离及受影响布局验收' for api in (26, 29, 31, 33, 35)},
    'API34-REALME-AFFECTED': 'realme API34受影响真机回归，绑定本轮APK',
    'ARM64-JNI': '实际ARM64进程JNI约定用例及最终句柄释放',
    'ARM32-JNI': '实际ARM32进程JNI约定用例及最终句柄释放',
    'SAFE-STOP-ACCOUNT-REPAIR': '安全停止/账号保护/确认取消/客户端100秒/最多一次重登无退化',
    'MAIN-SAME-SIGNATURE-INSTALL': '当前主APK在指定真机同签名覆盖安装；不清主包数据',
    'CURRENT-MANUAL-REAL-NETWORK': '仅用户手动认证的本轮受控实网证据，不能用隔离结果替代',
    'FINAL-STATIC-APK': '双ARM主包、隔离入口排除、签名、适用ELF与最终ZIP对齐',
    'PROTECTED-BASELINE-UNCHANGED': '阶段前后保护文件实算一致',
    'ENVIRONMENT-RESTORATION': '当前修订测试设置恢复及模拟器进程退出可核验',
}


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest().upper()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def checked_status(value):
    ensure(value in STATES, 'Unrecognized result status; review the source evidence')
    return value


def relative_file(root, relative):
    ensure(isinstance(relative, str), 'Relative path must be text')
    path = Path(relative)
    result = (root / path).resolve()
    ensure(not path.is_absolute() and result.is_relative_to(root.resolve()), 'Path escapes selected root')
    ensure(result.is_file(), 'Required input file is missing')
    return result


def entries(path):
    data = load(path)
    result = data if isinstance(data, list) else data.get('files', [])
    ensure(result and len({x['path'] for x in result}) == len(result), 'Empty or duplicate source manifest')
    return result


def verify_manifest(root, manifest, check_extras=False):
    expected = set()
    for item in manifest:
        path = relative_file(root, item['path'])
        ensure(path.suffix.lower() not in PRIVATE_SUFFIXES, 'Private-key-like file in source input')
        ensure(sha(path) == item['sha256'].upper(), 'Source content differs from its manifest')
        expected.add(Path(item['path']).as_posix())
    if check_extras:
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
                  and p.relative_to(root).as_posix() != 'local.properties'
                  and not p.relative_to(root).as_posix().startswith(SOURCE_EXCLUDES)}
        ensure(actual == expected, 'Unlisted source input or missing source file; rebuild/review manifest')


# Explicit typed evidence keys, recursively applied. No commands, paths, text dumps,
# serial/deviceAlias, exception messages, credentials, network identities or stderr.
TEXT_KEYS = {'testId', 'mode', 'status', 'case', 'id', 'apiName', 'model', 'manufacturer',
             'package', 'versionName', 'loadedAbi', 'name', 'phase', 'error', 'stop',
             'heartbeatResult', 'internetEvidence', 'schedulerMode', 'navigationRequested',
             'cutoutRequested', 'navigationActual', 'fontRequested', 'cleanup', 'exception',
             'exceptionType', 'protocolCode', 'pageTitle', 'expectedTitle', 'selectedTitle',
             'foregroundPackage', 'activePage', 'expectedPage', 'type', 'severity', 'ruleId'}
NUMERIC_KEYS = {'api', 'versionCode', 'pageSize', 'nativeBits', 'malformedRejected', 'cycles',
                'syntheticAlgorithms', 'allocationFailurePositionsPerAlgorithm', 'handlesAfter',
                'serviceCommands', 'line', 'retries', 'heartbeatIntervalSeconds', 'heartbeatDueInMs',
                'heartbeatAgeMs', 'waitBudgetMs', 'waitElapsedMs', 'loginRequests', 'logoutRequests',
                'keepRequests', 'minimumKeepRequests', 'syntheticErrorsRemaining', 'historyStartWall',
                'currentRunFailureEvents', 'minimumCurrentRunFailureEvents', 'elapsed', 'handles',
                'threadsTotal', 'threadsWithoutFixture', 'platformPools', 'ownedPools', 'calls',
                'deadlines', 'callbacks', 'jniHandlesIncludingFixture', 'nativeBytes', 'fd',
                'discoveryRequests', 'generation', 'requests', 'acceptedSockets', 'fontScale',
                'page', 'pageIndex', 'scrollY', 'exitCode', 'cleanupExit', 'width', 'height',
                'errors', 'warnings', 'truncatedRecords', 'rejectedRecords', 'unreadableFiles'}
BOOLEAN_KEYS = {'process64', 'desired', 'exactAlarmCapable', 'interactive', 'idle',
                'snapshotUnchanged', 'installSuccess', 'installedHashMatched', 'completed',
                'reportedFailure', 'visible', 'textFits', 'clickable', 'imeVisible',
                'foregroundVerified', 'pass', 'systemBarsClear', 'cutoutVerified'}
NESTED_KEYS = {'result', 'cases', 'expected', 'actual', 'observedHeartbeatFailure', 'instrumentation',
               'screens', 'checks', 'environment', 'restoration'}
ABI_KEYS = {'abis', 'supportedAbis', 'apkAbis'}
TEXT_KEYS |= {'label', 'contentMarker', 'activity', 'captureKind', 'interaction', 'failedStep',
              'installedPrimaryAbi', 'processAbi', 'navigation', 'cutout', 'manualOff',
              'installOutcome', 'actor', 'action', 'outcome', 'kind', 'role', 'time', 'startedAt', 'finishedAt',
              'internetResult', 'confirmationSource', 'timeBasis'}
TEXT_KEYS |= {'adapterClass', 'class', 'transformationClass', 'parentClass', 'substep'}
NUMERIC_KEYS |= {'activityInstance', 'windowId', 'businessClicks', 'sessionServicesCreated',
                 'selectedIndexBefore', 'selectedIndexAfter', 'actualNavigationMode', 'targetVersion',
                 'automaticLoginCount', 'automaticLogoutCount', 'automaticRepairCount', 'additionalNetworkProbeCount',
                 'mainForceStopCount', 'mainDataClearCount', 'validRowsInCurrentFile', 'invalidRowsInCurrentFile',
                 'wall', 'heartbeatAt', 'internetAt', 'nextRecoveryAt', 'heartbeatDueAt', 'heartbeatDelayMs', 'durationMs',
                 'loginCount', 'logoutCount', 'repairCount', 'userLoginCount', 'userLogoutCount', 'userRepairCount',
                 'maxLoginCount', 'maxLogoutCount', 'maxRepairCount', 'probeIntervalSeconds', 'maxObservationSeconds',
                 'observationSeconds', 'count', 'matchedFiles', 'changedFiles', 'missingFiles', 'addedFiles', 'fileCount'}
NUMERIC_KEYS |= {'measuredWidth', 'measuredHeight', 'maxWidth', 'maxLines', 'textSize',
                 'parentWidth', 'layoutParamWidth', 'layoutParamHeight', 'layoutWidth',
                 'lineCount', 'left', 'right', 'bottom', 'ellipsis', 'originatingWindowId',
                 'matchCount', 'visibleCount', 'snapshotCount', 'newDistinctEventsAfterInitialSnapshot',
                 'mainApplicationActions', 'historicalAvdDeletes', 'globalAdbServerActions'}
BOOLEAN_KEYS |= {'fullyVisible', 'enabled', 'businessClickInvoked', 'systemBarVisualReviewRequired',
                 'sessionServicePresent', 'idleForInstall', 'instrumentationExitSuccess'}
BOOLEAN_KEYS |= {'horizontallyScrollable', 'attached', 'shown', 'adapterUnchanged', 'manualVisualRequired',
                 'packageMatches', 'insideSafeBounds'}
NESTED_KEYS |= {'controls', 'popupOptions', 'beforeInstall', 'beforeState', 'immediateBeforeInstallState',
                'installed', 'snapshot', 'events', 'lastEvent', 'rules', 'counts', 'userActions', 'groups'}
NESTED_KEYS |= {'popupDebug', 'createdRows', 'actualRows', 'actualCandidates', 'lines',
                'independentFailures', 'options', 'nodes', 'results'}
STATUS_KEYS = {'fullVisualAcceptance', 'identityStatus', 'appControlVisualStatus', 'systemStatusBarVisualStatus',
               'uploadCleanupStatus', 'visualStatus', 'screenshotArtifactStatus', 'textLayoutStatus', 'manualTextLayoutStatus',
               'whitelistCollection', 'reportedManualLogin', 'newHeartbeatInWindow', 'newHttpsInWindow'}
GEOMETRY_KEYS = {'bounds', 'safeBounds', 'displayBounds', 'systemInsets', 'cutoutInsets', 'imeInsets'}
NARRATIVE_KEYS = {'expected', 'actual', 'reviewMethod', 'observation', 'limit', 'limitations', 'stopConditions', 'failureHandling', 'statement'}
HASH_KEYS = {'sha256', 'apkSha256', 'sourceId', 'sourceManifestSha256'}
PATH_KEYS = {'screenshot', 'artifactPath', 'evidence'}
PROBE_IDS = {'install-only', 'CompatProbe', 'RepairMenuProbe', 'StabilityProbe', 'DiscoveryProbe',
             'DiagnosticsProbe', 'InternetProbe', 'SessionProbe'}
AGGREGATE_KINDS = {'protected-baseline', 'ui-visual-review', 'api-matrix', 'manual-network', 'manual-action'}
ROOT_DOCUMENTS = ('README.md', 'AGENTS.md', '.gitignore', 'docs/CURRENT_STATUS.md', 'docs/NEXT_PROMPT.md',
                  'docs/BUILD_AND_INSTALL.md', 'docs/FULL_WORKFLOW.md', 'docs/USER_GUIDE.md')


def safe_relative(value):
    ensure(isinstance(value, str) and '\\' not in value and ':' not in value and '\x00' not in value,
           'Evidence path must be a safe slash-separated relative path')
    ensure(not value.startswith('/') and '..' not in Path(value).parts, 'Unsafe evidence path')
    return value


def abi_list(value, device_capabilities=False):
    if isinstance(value, str):
        value = [part.strip() for part in value.split(',') if part.strip()]
    ensure(isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value), 'Invalid ABI collection')
    allowed = {'arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'}
    if device_capabilities:
        allowed.add('armeabi')  # Device-reported legacy capability; never an APK delivery ABI.
    ensure(set(value) <= allowed, 'Unexpected ABI identifier')
    return list(dict.fromkeys(value))


def evidence_projection(value, depth=0):
    ensure(depth <= 12, 'Evidence exceeds supported nesting')
    if isinstance(value, list):
        ensure(len(value) <= 2000, 'Evidence list too large for curated delivery')
        return [evidence_projection(x, depth + 1) for x in value if isinstance(x, dict)]
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key == 'status' or key in STATUS_KEYS:
            result[key] = checked_status(item)
        elif key == 'api' and isinstance(item, str) and re.fullmatch(r'[0-9]{1,3}', item):
            result[key] = int(item)
        elif key in HASH_KEYS and isinstance(item, str):
            ensure(re.fullmatch(r'[A-Fa-f0-9]{64}', item), 'Invalid evidence hash')
            result[key] = item.upper()
        elif key in PATH_KEYS and isinstance(item, str):
            result[key] = safe_relative(item)
        elif key in GEOMETRY_KEYS and isinstance(item, str):
            ensure(len(item) <= 200 and re.fullmatch(r'[A-Za-z0-9{},=\[\] .:+()-]+', item), 'Invalid geometry label')
            result[key] = item
        elif key in NARRATIVE_KEYS and isinstance(item, str):
            ensure(len(item) <= 2000 and not re.search(r'[A-Za-z]:[\\/]|https?://', item), 'Unreviewed narrative path or URL')
            result[key] = item
        elif key in NARRATIVE_KEYS and isinstance(item, list):
            ensure(len(item) <= 30 and all(isinstance(x, str) and len(x) <= 1000 and
                   not re.search(r'[A-Za-z]:[\\/]|https?://', x) for x in item), 'Invalid narrative list')
            result[key] = item
        elif key in NUMERIC_KEYS and (item is None or isinstance(item, (int, float)) and not isinstance(item, bool)):
            result[key] = item
        elif key in BOOLEAN_KEYS and isinstance(item, bool):
            result[key] = item
        elif key in TEXT_KEYS and isinstance(item, str) and len(item) <= 200:
            # Text is restricted to already allowlisted labels, enums and component identifiers.
            ensure(not re.search(r'[A-Za-z]:[\\/]|(?:https?://)|\r|\n', item), 'Unexpected path/URL in public evidence label')
            result[key] = item
        elif key in ABI_KEYS and isinstance(item, (str, list, tuple)):
            result[key] = abi_list(item, device_capabilities=key in ('abis', 'supportedAbis'))
        elif key in NESTED_KEYS and isinstance(item, (dict, list)):
            result[key] = evidence_projection(item, depth + 1)
    return result


def combine(statuses):
    if not statuses:
        return 'NOT_RUN'
    for state in ('FAIL', 'BLOCKED', 'NOT_RUN'):
        if state in statuses:
            return state
    return 'PASS'


def zip_bytes(files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            ensure(not name.startswith('/') and '..' not in Path(name).parts, 'Invalid archive member')
            archive.writestr(name, data)
    return result.getvalue()


def apk_payload(path):
    """Bind a reviewed unsigned/aligned build artifact to its final signed APK payload."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if re.fullmatch(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', name, re.I):
                continue
            data = archive.read(name)
            digest.update(name.encode('utf-8') + b'\0' + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest().upper()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iteration', required=True)
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--build-record', action='append', required=True)
    parser.add_argument('--reviewed-script', action='append', required=True)
    parser.add_argument('--extra-result', action='append', default=[])
    parser.add_argument('--reviewed-screenshot', action='append', default=[])
    parser.add_argument('--reviewed-screenshot-list')
    parser.add_argument('--gate-plan', required=True)
    parser.add_argument('--review-corrections')
    parser.add_argument('--reviewed-summary')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    ensure(re.fullmatch(r'r[1-9][0-9]*', args.iteration), 'Select an explicit build iteration such as r4')
    stage = require_mutable_stage()
    source = stage / 'source'
    baseline = Path(args.baseline_source).resolve()
    baseline_manifest = stage / 'evidence/source-manifest.json'
    original_manifest = stage / 'evidence/original-source-manifest.json'
    final_manifest = stage / f'evidence/build-input-{args.iteration}.json'
    ensure(sha(baseline_manifest) == PUBLISHED_MANIFEST, 'Published baseline manifest identity mismatch')
    ensure(sha(original_manifest) == ORIGINAL_MANIFEST, 'Original APK input manifest identity mismatch')
    before = entries(baseline_manifest); after = entries(final_manifest)
    ensure(len(before) == 233, 'Published baseline must contain 233 files')
    verify_manifest(baseline, before)
    verify_manifest(source, after, check_extras=True)
    source_id = sha(final_manifest)
    created = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    audit_path = stage / f'evidence/{args.iteration}-static/apk-audit.json'
    audit = load(audit_path)
    ensure(audit['sourceId'] == source_id and audit['sourceManifestSha256'] == source_id, 'Static audit is for another source input')
    ensure(audit['status'] == 'PASS' and len(audit['apks']) == 4, 'Review final static audit before packaging')
    apks = audit['apks']
    apk_hashes = set()
    for item in apks:
        path = relative_file(OUTPUT, item['file'])
        ensure(item['status'] == 'PASS' and sha(path) == item['sha256'], 'Final APK changed or was not statically accepted')
        ensure(item['certificateSha256'] == CERT, 'APK certificate mismatch')
        apk_hashes.add(item['sha256'])
        ensure(not (OUTPUT / (item['file'] + '.idsig')).exists(),
               'Archive final idsig sidecars under this stage pack directory before packaging; do not delete them. They are not selected delivery files.')

    # Prepare everything in memory; no artifact is written until all checks succeed.
    deliver = {}
    references = []
    def local_reference(path, role):
        path = path.resolve()
        ensure(path.is_relative_to(stage), 'Evidence must belong to this stage')
        row = {'archivePath': path.relative_to(stage).as_posix(), 'sha256': sha(path), 'role': role,
               'includedOriginal': False}
        references.append(row)
        return row
    deliver['source-manifest.json'] = final_manifest.read_bytes()
    source_zip_files = {'source/' + x['path']: relative_file(source, x['path']).read_bytes() for x in after}
    supplements = {}; supplement_changes = []
    baseline_repository = baseline.parent
    for name in ROOT_DOCUMENTS:
        current = relative_file(stage, name)
        source_zip_files[name] = current.read_bytes()
        supplements[name] = {'path': name, 'sha256': sha(current), 'scope': 'delivery-docs-outside-build-input'}
        original = baseline_repository / name
        old_hash = sha(original) if original.is_file() else None
        if old_hash != sha(current):
            supplement_changes.append({'path': name, 'changeType': 'M' if old_hash else 'A',
                'beforePath': name if old_hash else None, 'beforeSha256': old_hash, 'afterSha256': sha(current)})
    ensure(audit['versionName'] in source_zip_files['README.md'].decode('utf-8-sig') and
           audit['versionName'] in source_zip_files['docs/CURRENT_STATUS.md'].decode('utf-8-sig'),
           'Update delivery root README/current status for the final revision before packaging')
    source_zip_files['BUILD_INPUT_BOUNDARY.txt'] = (
        f'本源码包顶层README/docs是本轮交付入口。实际Android构建输入仅source/内{len(after)}文件，'
        f'对应source-manifest.json SHA256={source_id}。顶层说明及支持脚本另见supplement-manifest.json，'
        '不倒签为Android构建输入。source/内历史README不替代顶层说明。\n').encode('utf-8')
    before_map = {x['path']: x for x in before}; after_map = {x['path']: x for x in after}
    changes = []; patches = []; redactions = []
    def diff_text(data, path, side):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            return None
        lines = text.splitlines(keepends=True)
        # Legacy baseline build scripts contain a signing-password literal. Do not
        # disclose it even as a removed patch line. No literal is copied into this script.
        if path == 'build-stage.ps1' and side == 'before':
            # Quarantine this entire legacy input, including possible multiline literals.
            # The current script is shipped separately in the verified source archive.
            redactions.append({'path': path, 'side': side, 'scope': 'entire legacy build script',
                               'reason': 'Legacy signing-password literal withheld, including multiline continuations'})
            return ['# <REDACTED_LEGACY_BUILD_SCRIPT_WITH_SIGNING_PASSWORD_LITERAL>\n']
        if path.endswith('.ps1'):
            for index, line in enumerate(lines):
                if re.search(r'password|(?:ks|store|key)-?pass', line, re.I):
                    lines[index] = '# <REDACTED_SIGNING_PASSWORD_RELATED_LINE>\n'
                    redactions.append({'path': path, 'side': side, 'line': index + 1,
                                       'reason': 'Signing password-related statement withheld; original hashes remain authoritative'})
        return lines
    for name in sorted(before_map.keys() | after_map.keys()):
        old = before_map.get(name); new = after_map.get(name)
        if old and new and old['sha256'] == new['sha256']:
            continue
        changes.append({'path': 'source/' + name, 'changeType': 'A' if old is None else 'D' if new is None else 'M',
                        'beforeSha256': old['sha256'] if old else None, 'afterSha256': new['sha256'] if new else None})
        left = diff_text(relative_file(baseline, name).read_bytes(), name, 'before') if old else []
        right = diff_text(relative_file(source, name).read_bytes(), name, 'after') if new else []
        if left is None or right is None:
            patches.append(f'Binary change: {name}; see changes.json for hashes.\n')
        else:
            patches.extend(difflib.unified_diff(left, right, fromfile='published-baseline/' + name, tofile='current-source/' + name))
    deliver['changes.json'] = encoded(changes)
    deliver['source-diff.txt'] = ('REVIEW-ONLY REDACTED DIFF: not guaranteed to be directly git-applicable.\n'
                                  'Signing-password-related PowerShell lines are explicit placeholders.\n\n' + ''.join(patches)).encode('utf-8')
    deliver['diff-redactions.json'] = encoded(redactions)
    lineage = {'publishedBaselineManifestSha256': PUBLISHED_MANIFEST, 'publishedBaselineFiles': 233,
               'originalApkSourceManifestSha256': ORIGINAL_MANIFEST,
               'originalBuildBinding': load(stage / 'evidence/original-build-binding.json'),
               'publicationChanges': load(stage / 'evidence/publication-changes.json'),
               'currentSourceManifestSha256': source_id,
               'note': '原APK继续绑定原始C83清单；发布副本仅一份文档脱敏，不能倒签为原APK输入。本轮APK另绑定本轮实际输入。'}
    ensure(len(lineage['publicationChanges']) == 1, 'Review unexpected publication-baseline changes')
    ensure(lineage['originalBuildBinding']['sourceManifestSha256'] == ORIGINAL_MANIFEST,
           'Original build binding does not refer to the original input manifest')
    publication = lineage['publicationChanges'][0]
    ensure(publication['path'] == 'source/docs/阶段1复现与真机操作.md' and
           publication['afterSha256'] == before_map['docs/阶段1复现与真机操作.md']['sha256'],
           'Published baseline is not the recorded single-document privacy revision')
    lineage['publicationChanges'] = [{('changeType' if key == 'status' else key): value
                                      for key, value in publication.items()}]
    deliver['source-lineage.json'] = encoded(lineage)
    deliver['evidence/original-source-manifest.json'] = original_manifest.read_bytes()
    deliver['evidence/published-baseline-source-manifest.json'] = baseline_manifest.read_bytes()
    scripts = {}
    for name in sorted(set(args.reviewed_script)):
        ensure(name in SCRIPT_CANDIDATES, 'Script is not in the reviewable support-script allowlist')
        scripts[name] = relative_file(stage, name).read_bytes()
        text = scripts[name].decode('utf-8-sig')
        ensure(not re.search(r'''(?im)\bserial\s*=\s*['"][^'"]+['"]''', text), 'Hardcoded serial assignment in reviewed support script')
        ensure(not re.search(r'''(?i)['"]--serial['"]\s*,\s*['"][^'"]+['"]''', text), 'Hardcoded serial argument in reviewed support script')
        digest = hashlib.sha256(scripts[name]).hexdigest().upper()
        supplements['support/' + name] = {'path': 'support/' + name, 'archiveMember': 'scripts.zip/' + name,
                                        'sha256': digest, 'scope': 'support-script-outside-build-input'}
        originals = [baseline_repository / name, baseline_repository / 'tools/v33-history' / name]
        original = next((p for p in originals if p.is_file()), None)
        old_hash = sha(original) if original else None
        if digest != old_hash:
            supplement_changes.append({'path': 'support/' + name, 'changeType': 'M' if original else 'A',
                'beforePath': original.relative_to(baseline_repository).as_posix() if original else None,
                'beforeSha256': old_hash, 'afterSha256': digest})
    deliver['scripts.zip'] = zip_bytes(scripts)
    for selected_name, dependencies in {
        'start_emulator.py': {'emulator_process_guard.py', 'stage_guard.py', 'adb_client.py'},
        'restore_revision.py': {'emulator_process_guard.py', 'stage_guard.py', 'adb_client.py'},
        'run_realme_batch.py': {'stage_guard.py', 'adb_client.py', 'run_device.py', 'run_ui.py'},
        'run_remaining_matrix.py': {'start_emulator.py', 'restore_revision.py', 'matrix-suite.py'},
    }.items():
        if selected_name in scripts:
            ensure(dependencies <= scripts.keys(), 'Reviewed script dependency is absent from the delivery selection')
    deliver['script-manifest.json'] = encoded([{'path': name, 'sha256': hashlib.sha256(data).hexdigest().upper(),
                                                'selection': 'explicit --reviewed-script'} for name, data in scripts.items()])
    deliver['supplement-manifest.json'] = encoded({'notBuildInputs': True, 'files': list(supplements.values()),
        'note': '顶层说明/支持脚本的交付清单；source-manifest.json仍只含实际Android构建输入。生成的BUILD_INPUT_BOUNDARY及清单本身不包含于自身哈希。'})
    deliver['supplement-changes.json'] = encoded({'baseline': 'published repository root and tools/v33-history',
        'changes': supplement_changes, 'note': '与changes.json合看覆盖本轮源码、交付说明和选定支持脚本变化；不将缓存/运行证据当作源码。'})
    source_zip_files['source-manifest.json'] = final_manifest.read_bytes()
    source_zip_files['supplement-manifest.json'] = deliver['supplement-manifest.json']
    deliver['source.zip'] = zip_bytes(source_zip_files)

    final_rows = []; histories = []; excluded = []; raw_by_label = {}
    corrections = {}
    if args.review_corrections:
        correction_path = relative_file(stage, args.review_corrections)
        local_reference(correction_path, 'explicit reviewed status corrections; original records preserved')
        for correction in load(correction_path):
            ensure(set(correction) == {'label', 'rawSha256', 'declaredStatus', 'status', 'reason'}, 'Unexpected status correction fields')
            ensure(correction['label'] not in corrections and correction['declaredStatus'] == 'PASS' and correction['status'] == 'BLOCKED',
                   'Only explicit PASS-to-BLOCKED restoration evidence corrections are supported')
            ensure(isinstance(correction['reason'], str) and 0 < len(correction['reason']) <= 1000 and
                   not re.search(r'[A-Za-z]:[\\/]|https?://', correction['reason']), 'Unsafe correction explanation')
            corrections[correction['label']] = correction
    used_corrections = set()
    paths = list((stage / 'evidence').glob('r*-*/result.json'))
    extras = [relative_file(stage, x) for x in args.extra_result]
    aggregate_paths = [p for p in extras if load(p).get('kind') in AGGREGATE_KINDS]
    paths += [p for p in extras if p not in aggregate_paths]
    for path in sorted(set(paths)):
        raw = load(path); label = path.parent.name if path.name == 'result.json' else path.stem
        state = checked_status(raw.get('status', 'NOT_RUN'))
        ref = local_reference(path, 'selected result' if label.startswith(args.iteration + '-') else 'historical result')
        row = {'testId': label, 'probe': raw.get('testId', 'unspecified'), 'status': state,
               'sourceId': raw.get('sourceId'), 'apkSha256': raw.get('apkSha256'), 'time': raw.get('time'),
               'expected': '本条脚本约定断言与恢复清理通过；完整范围见对应脚本及验收门槛',
               'actual': evidence_projection(raw), 'evidence': ref}
        if not label.startswith(args.iteration + '-'):
            row['scope'] = 'historical-iteration-only'
            if state == 'BLOCKED' and 'paused' in raw.get('reason', '').lower():
                row['blockKind'] = 'revision-paused'
                row['note'] = '当时因修订暂停；不是永久环境缺口，也不是最终构建的测试结果。'
            histories.append(row)
            continue
        if raw.get('sourceId') != source_id or raw.get('apkSha256') not in apk_hashes:
            excluded.append({'testId': label, 'status': 'NOT_RUN', 'reason': 'Current label does not match final source and APK', 'evidence': ref})
            continue
        if label in corrections:
            correction = corrections[label]
            ensure(raw.get('testId') in ('RESTORE-EMULATOR', 'RESTORE-ISOLATION') and state == 'PASS' and
                   sha(path) == correction['rawSha256'].upper(), 'Correction does not bind the exact declared restoration result')
            row['declaredStatus'] = state
            state = row['status'] = correction['status']
            row['actual']['declaredStatus'] = row['actual'].get('status')
            row['actual']['status'] = state
            row['assessmentCorrection'] = correction['reason']
            used_corrections.add(label)
        ensure(label not in raw_by_label, 'Duplicate result label')
        if state == 'PASS':
            nested = raw.get('result', {})
            ensure(not isinstance(nested, dict) or nested.get('status', 'PASS') == 'PASS', 'Result disagrees with inner probe status')
            if raw.get('testId') in PROBE_IDS:
                ensure(type(raw.get('cleanupExit')) is int and raw['cleanupExit'] == 0,
                       'PASS run_device result requires an explicit integer cleanupExit=0')
            elif raw.get('testId') == 'S1-UI':
                ensure(raw.get('restoration') and all(x.get('status') == 'PASS' for x in raw['restoration']),
                       'UI PASS requires explicit successful restoration evidence')
            elif raw.get('testId') == 'MAIN-INSTALL':
                ensure(raw.get('installOutcome') == 'SUCCESS' and raw.get('uploadCleanupStatus') == 'PASS',
                       'Main installation PASS requires successful installation and upload cleanup')
            elif raw.get('testId') in ('RESTORE-EMULATOR', 'RESTORE-ISOLATION'):
                checks = raw.get('checks')
                ensure(isinstance(checks, list) and checks and all(x.get('status') == 'PASS' for x in checks),
                       'Restoration PASS requires nonempty explicit all-PASS checks')
                ensure(all(type(raw.get(k)) is int and raw[k] == 0 for k in
                           ('mainApplicationActions', 'historicalAvdDeletes', 'globalAdbServerActions')),
                       'Restoration PASS requires explicit zero main/global/history actions')
                if raw['testId'] == 'RESTORE-EMULATOR':
                    ensure({'emulator-disconnected', 'emulator-process-tree-exited'} <= {x.get('id') for x in checks},
                           'Emulator restoration PASS requires both ADB disconnection and verified process-tree exit')
            elif raw.get('testId') not in ('MAIN-SNAPSHOT', 'MAIN-PREFLIGHT'):
                raise ValueError('Unknown leaf PASS type: explicitly review its cleanup contract before packaging')
        # Preserve and verify complete per-image metadata, without implicitly marking visual acceptance.
        image_rows = raw.get('result', {}).get('screens', []) if isinstance(raw.get('result'), dict) else []
        for image in image_rows:
            ensure(re.fullmatch(r'[A-Za-z0-9-]+', image['name']), 'Unsafe screenshot label')
            image_path = path.parent / (image['name'] + '.png')
            ensure(image_path.is_file() and sha(image_path) == image['sha256'].upper(), 'Screenshot file/hash does not match probe record')
            local_reference(image_path, 'current run screenshot bound to page metadata')
        row['scope'] = 'current-final-build'; final_rows.append(row); raw_by_label[label] = (raw, row)
        deliver['evidence/results/' + label + '.json'] = encoded(row)
    ensure(used_corrections == set(corrections), 'A reviewed correction did not match an included final result')
    # Static audit is intentionally a separate result, not a device-compatibility claim.
    static_label = args.iteration + '-static'
    static_row = {'testId': static_label, 'status': 'PASS', 'sourceId': source_id, 'apkSha256': None,
                  'time': audit.get('time'), 'expected': 'APK identity/signature/ABI/ELF/ZIP/test-entrypoint static checks',
                  'actual': {'apks': apks, 'lint': audit['lint']}, 'evidence': local_reference(audit_path, 'final static audit'),
                  'scope': 'static-only'}
    final_rows.append(static_row); raw_by_label[static_label] = (audit, static_row)
    deliver['evidence/static-apk-audit.json'] = encoded(static_row)
    def referenced_input(ref):
        ensure(isinstance(ref, dict) and set(ref) <= {'path', 'sha256', 'sourceId', 'apkSha256'}, 'Unexpected aggregate reference fields')
        path = relative_file(stage, safe_relative(ref['path']))
        ensure(path.is_relative_to(stage / 'evidence') and path.suffix == '.json', 'Aggregate may reference stage evidence JSON only')
        ensure(sha(path) == ref['sha256'].upper(), 'Aggregate child evidence SHA mismatch')
        return path

    for path in aggregate_paths:
        raw = load(path)
        ensure(raw['kind'] in AGGREGATE_KINDS and raw.get('iteration') == args.iteration and raw.get('sourceId') == source_id,
               'Aggregate must explicitly bind the final iteration and source')
        label = raw.get('label', path.stem)
        ensure(re.fullmatch(r'[A-Za-z0-9-]+', label) and label not in raw_by_label, 'Invalid or duplicate aggregate label')
        state = checked_status(raw.get('status', 'NOT_RUN'))
        children = []
        for ref in raw.get('children', []):
            child_path = referenced_input(ref); child = load(child_path)
            ensure(child.get('sourceId') == ref.get('sourceId') == source_id and
                   child.get('apkSha256') == ref.get('apkSha256') and child.get('apkSha256') in apk_hashes,
                   'Aggregate child must match the actual final source and one final APK')
            child_label = child_path.parent.name if child_path.name == 'result.json' else child_path.stem
            ensure(child_label in raw_by_label, 'Aggregate child was not selected as a validated current run')
            ensure(raw_by_label[child_label][1]['evidence']['sha256'] == sha(child_path), 'Aggregate child differs from selected result')
            children.append((child_path, child, raw_by_label[child_label][1]))
        actual = evidence_projection(raw)
        if raw['kind'] == 'protected-baseline':
            before_path = referenced_input(raw['before']); after_path = referenced_input(raw['after'])
            before_rows = load(before_path); after_rows = load(after_path)
            ensure(isinstance(before_rows, list) and isinstance(after_rows, list) and before_rows and after_rows,
                   'Protected evidence requires nonempty before/after snapshots')
            # Normalize Windows spelling only; do not resolve filesystem aliases.
            left = {x['path'].replace('\\', '/').casefold(): x['sha256'].upper() for x in before_rows}
            right = {x['path'].replace('\\', '/').casefold(): x['sha256'].upper() for x in after_rows}
            ensure(len(before_rows) == 1442, 'Protected comparison must start from the recorded 1442-file baseline')
            ensure(len(left) == len(before_rows) and len(right) == len(after_rows), 'Duplicate protected snapshot path')
            ensure(all(re.fullmatch(r'[A-F0-9]{64}', x) for x in [*left.values(), *right.values()]), 'Invalid protected file digest')
            comparison = {'fileCount': len(left), 'matchedFiles': sum(left[k] == right[k] for k in left.keys() & right.keys()),
                          'changedFiles': sum(left[k] != right[k] for k in left.keys() & right.keys()),
                          'missingFiles': len(left.keys() - right.keys()), 'addedFiles': len(right.keys() - left.keys())}
            derived = 'PASS' if left == right else 'FAIL'
            ensure(state == derived, 'Protected comparison declared status disagrees with actual hashes')
            actual['comparison'] = comparison
            actual['before'] = local_reference(before_path, 'protected snapshot: paths withheld, hashes compared')
            actual['after'] = local_reference(after_path, 'protected snapshot: paths withheld, hashes compared')
        elif raw['kind'] == 'ui-visual-review':
            ensure(children and raw.get('screens'), 'Visual review must identify child runs and individual screenshots')
            available = {}
            for child_path, child, _ in children:
                ensure(child.get('package') == 'org.esurfing.hunan.isolation', 'Visual images must come from the isolated app')
                for image in child.get('result', {}).get('screens', []):
                    available[(child_path.parent / (image['name'] + '.png')).resolve()] = image
            reviewed = set(); visual_states = []
            actual['screens'] = []
            for image in raw['screens']:
                relative = safe_relative(image['evidence'])
                image_path = relative_file(stage, relative if relative.startswith('evidence/') else 'evidence/' + relative)
                ensure(image_path in available and sha(image_path) == image['sha256'].upper() == available[image_path]['sha256'].upper(),
                       'Visual screenshot is not the exact image captured by its bound current run')
                recorded = available[image_path]
                ensure(image.get('pageIndex') == recorded.get('pageIndex') and image.get('pageTitle') == recorded.get('pageTitle'),
                       'Visual review page identity differs from probe metadata')
                image_states = [checked_status(image[key]) for key in ('identityStatus', 'appControlVisualStatus', 'systemStatusBarVisualStatus')]
                visual_states.extend(image_states); reviewed.add(image_path)
                row = evidence_projection(recorded)
                row.update(evidence_projection(image))
                row['artifactPath'] = f'evidence/screenshots/{image_path.parent.name}/{image_path.name}'
                actual['screens'].append(row)
                deliver[row['artifactPath']] = image_path.read_bytes()
                local_reference(image_path, 'explicitly reviewed per-image visual evidence')
            if state == 'PASS':
                ensure(reviewed == set(available) and all(x == 'PASS' for x in visual_states),
                       'Visual PASS requires all child screenshots and all declared visual checks to pass')
        elif raw['kind'] == 'api-matrix':
            ensure(children, 'API matrix requires child runs')
            groups = collections.defaultdict(list)
            for _, child, row in children:
                api = child.get('api')
                if isinstance(api, str) and re.fullmatch(r'[0-9]{1,3}', api): api = int(api)
                ensure(api is None or type(api) is int, 'Invalid matrix API')
                # run_ui's `abis` is a comma-separated DEVICE capability list;
                # package ABIs come from the final APK audit, never from that list.
                package_abis = next(x['abis'] for x in apks if x['sha256'] == child['apkSha256'])
                supported = child.get('supportedAbis', child.get('abis', []))
                key = (api, child.get('model'), child.get('pageSize'), tuple(abi_list(package_abis)), tuple(abi_list(supported, device_capabilities=True)))
                groups[key].append(row)
            actual['groups'] = [{'environment': {'api': key[0], 'model': key[1], 'pageSize': key[2],
                                                'apkAbis': list(key[3]), 'supportedAbis': list(key[4])},
                                 'status': combine([row['status'] for row in rows]), 'testIds': [row['testId'] for row in rows]}
                                for key, rows in sorted(groups.items(), key=lambda item: str(item[0]))]
            if state == 'PASS':
                ensure(all(row['status'] == 'PASS' for _, _, row in children), 'Matrix PASS includes a non-PASS child')
        else:
            ensure(isinstance(raw.get('userActions'), list), 'Manual evidence requires explicit user action records')
            for action in raw['userActions']:
                ensure(action.get('actor') == 'user' and action.get('action') in
                       {'manual-stop', 'manual-login', 'manual-logout', 'manual-repair-confirmation', 'install-approval'},
                       'Unknown actor/action in manual record')
                ensure(isinstance(action.get('time'), str), 'Manual action requires its recorded time')
            if raw['kind'] == 'manual-network':
                ensure(children and isinstance(raw.get('counts'), dict) and isinstance(raw.get('rules'), dict),
                       'Manual network evidence requires observed child snapshots, rules and actual counts')
                counts = raw['counts']; rules = raw['rules']
                for key in ('automaticLoginCount', 'automaticLogoutCount', 'automaticRepairCount'):
                    ensure(type(counts.get(key)) is int and counts[key] == 0, 'Real authentication must remain user-operated')
                for count_key, maximum_key in (('userLoginCount', 'maxLoginCount'), ('userLogoutCount', 'maxLogoutCount'), ('userRepairCount', 'maxRepairCount')):
                    ensure(type(counts.get(count_key)) is int and type(rules.get(maximum_key)) is int and
                           0 <= counts[count_key] <= rules[maximum_key], 'Manual action count exceeds or lacks the reviewed budget')
                if state == 'PASS':
                    observed_events = [child.get('snapshot', {}).get('events', {}).get('lastEvent') or {}
                                       for _, child, child_row in children
                                       if child.get('testId') == 'MAIN-SNAPSHOT' and child_row['status'] == 'PASS']
                    ensure(len(observed_events) >= 2 and
                           any(x.get('heartbeatAt', 0) > observed_events[0].get('heartbeatAt', 0) for x in observed_events[1:]) and
                           any(x.get('internetAt', 0) > observed_events[0].get('internetAt', 0) for x in observed_events[1:]),
                           'Stored repeated successes cannot establish new heartbeat/HTTPS evidence in the observation window')
                    ensure(type(rules.get('maxObservationSeconds')) is int and rules['maxObservationSeconds'] > 0 and
                           isinstance(counts.get('observationSeconds'), (int, float)) and
                           0 < counts['observationSeconds'] <= rules['maxObservationSeconds'], 'Manual observation lacks or exceeds its bounded duration')
                    start = datetime.datetime.fromisoformat(raw['startedAt'].replace('Z', '+00:00'))
                    end = datetime.datetime.fromisoformat(raw['finishedAt'].replace('Z', '+00:00'))
                    ensure(start.tzinfo is not None and end.tzinfo is not None and
                           0 <= (end - start).total_seconds() <= rules['maxObservationSeconds'], 'Manual observation window is invalid or exceeds budget')
                    observed_success = False
                    for _, child, child_row in children:
                        if child.get('testId') != 'MAIN-SNAPSHOT' or child_row['status'] != 'PASS': continue
                        sampled = datetime.datetime.fromisoformat(child['time'].replace('Z', '+00:00'))
                        snapshot = child.get('snapshot', {}); event = snapshot.get('events', {}).get('lastEvent') or {}
                        if not (start <= sampled <= end and snapshot.get('manualOff') == 'false' and
                                snapshot.get('sessionServicePresent') is True and event.get('desired') is True): continue
                        wall = event.get('wall', 0); heartbeat = event.get('heartbeatAt', 0); internet = event.get('internetAt', 0)
                        if (event.get('phase') == 'AUTHENTICATED' and event.get('heartbeatResult') == 'PASS' and
                                event.get('internetResult') == 'PASS' and event.get('internetEvidence') == 'HTTPS_VERIFIED' and
                                0 < heartbeat <= wall and 0 < internet <= wall and wall - internet <= 600000):
                            observed_success = True
                    ensure(counts['userLoginCount'] > 0 and observed_success,
                           'Real network PASS requires an active authenticated/heartbeat/HTTPS sample inside this reviewed observation window')
        row = {'testId': label, 'status': state, 'kind': raw['kind'], 'sourceId': source_id,
               'apkSha256': None, 'time': raw.get('time', raw.get('reviewedAt')),
               'expected': raw.get('expected', '该聚合项的已审查门槛'), 'actual': actual,
               'children': [{'testId': child_row['testId'], 'sourceId': source_id, 'apkSha256': child['apkSha256'],
                             'evidence': child_row['evidence']} for _, child, child_row in children],
               'evidence': local_reference(path, 'explicitly reviewed aggregate evidence'), 'scope': 'current-source-bound-aggregate'}
        final_rows.append(row); raw_by_label[label] = (raw, row)
        deliver['evidence/results/' + label + '.json'] = encoded(row)

    selected_screenshots = list(args.reviewed_screenshot)
    if args.reviewed_screenshot_list:
        selected = load(args.reviewed_screenshot_list)
        ensure(isinstance(selected, list) and all(isinstance(x, str) for x in selected), 'Screenshot selection must be a reviewed path list')
        selected_screenshots += selected
    for relative in selected_screenshots:
        path = relative_file(stage, relative); label = path.parent.name
        ensure(path.suffix.lower() == '.png' and label in raw_by_label, 'Screenshot is not from a selected final run')
        ensure(raw_by_label[label][0].get('package') == 'org.esurfing.hunan.isolation', 'Only reviewed isolated screenshots may be delivered')
        deliver[f'evidence/screenshots/{label}/{path.name}'] = path.read_bytes()
        local_reference(path, 'explicitly reviewed isolated screenshot')

    # Read names/paths only from private local configuration. Never read password env values.
    config = load(stage / 'tools.local.json')
    mapping = {str(source): '<SOURCE>', str(stage): '<STAGE>', str(OUTPUT): '<OUTPUT>',
               str(config['AndroidSdk']): '<ANDROID_SDK>', str(config['JdkHome']): '<JDK>',
               str(config['GradleExecutable']): '<GRADLE_EXECUTABLE>', str(config['TestKeystore']): '<EXISTING_TEST_KEYSTORE>'}
    replacements = []
    for actual, placeholder in mapping.items():
        replacements.extend([(actual.replace('\\', '/'), placeholder), (actual.replace('/', '\\'), placeholder)])
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    def public_command(value):
        if isinstance(value, dict):
            return {key: public_command(item) for key, item in value.items()}
        if isinstance(value, list):
            return [public_command(item) for item in value]
        if not isinstance(value, str):
            return value
        ensure(not re.search(r'\bpass:', value, re.I), 'Inline signing password found; refusing public command export')
        value = value.replace('env:' + config['SigningPasswordVariable'], 'env:<SIGNING_PASSWORD_ENV>')
        for actual, placeholder in replacements:
            value = re.sub(re.escape(actual), lambda _: placeholder, value, flags=re.I)
        ensure(not re.search(r'[A-Za-z]:[\\/]', value), 'Unmapped absolute command path; add an explicit reviewed mapping')
        return value
    command_records = []
    bound_apks = set()
    final_apks = {item['file']: OUTPUT / item['file'] for item in apks}
    for relative in args.build_record:
        directory = (stage / relative).resolve()
        ensure(directory.is_relative_to(stage / 'evidence') and directory.name.startswith('build-'), 'Select current-stage build evidence directories')
        build_command = load(directory / 'build-command.json')
        ensure(build_command['versionName'] == audit['versionName'] and build_command['versionCode'] == audit['versionCode'], 'Build record version mismatch')
        files = [directory / 'build-command.json', directory / 'build-exit.json']
        files += sorted(directory.glob('packaging-commands-*.json')) + sorted(directory.glob('packaging-exits-*.json'))
        for file in files:
            record = load(file)
            if file.name.startswith('packaging-commands-'):
                signing = [x for x in record if 'sign' in x.get('arguments', [])]
                ensure(len(signing) == 1, 'Expected one reviewed signing command')
                arguments = signing[0]['arguments']
                for flag in ('--ks-pass', '--key-pass'):
                    if flag in arguments:
                        ensure(arguments[arguments.index(flag) + 1] == 'env:' + config['SigningPasswordVariable'], 'Signing values must use the configured environment reference only')
                output_name = Path(arguments[arguments.index('--out') + 1]).name
                aligned = Path(arguments[-1]).resolve()
                ensure(output_name in final_apks and aligned.is_relative_to(stage / 'pack'), 'Packaging command points outside selected final artifacts')
                ensure(output_name not in bound_apks, 'Multiple selected build records for the same final APK')
                ensure(apk_payload(aligned) == apk_payload(final_apks[output_name]), 'Selected build payload differs from final APK; wrong build iteration')
                bound_apks.add(output_name)
            command_records.append({'localOriginal': local_reference(file, 'raw build command/exit retained locally'),
                                    'publicRecord': public_command(record)})
    ensure(bound_apks == set(final_apks), 'Build records must cover the payload of all four final APKs')
    deliver['build-commands-public.json'] = encoded({'pathPlaceholders': sorted(set(mapping.values())) + ['<SIGNING_PASSWORD_ENV>'],
        'note': '完整原始命令仅保留本地引用与哈希；对外参数显式映射路径，不包含口令值。构建目录由审查者显式选择，版本相同不能单独证明构建输入。',
        'records': command_records})
    toolchain = load(stage / 'evidence/toolchain-public.json')
    deliver['toolchain.json'] = encoded({key: toolchain[key] for key in ('jdk', 'gradle', 'agp', 'kotlin', 'components', 'compileSdk', 'minSdk', 'targetSdk', 'testCertificateSha256') if key in toolchain})

    plans = {key: {'testId': key, 'expected': description, 'evidenceLabels': [],
                   'required': key != 'CURRENT-MANUAL-REAL-NETWORK'} for key, description in DEFAULT_GATES.items()}
    plans['API36-SUPPLEMENTAL'] = {'testId': 'API36-SUPPLEMENTAL', 'expected': 'API36补充验证，保持targetSdk35', 'evidenceLabels': [], 'required': False}
    plans['FINAL-STATIC-APK']['evidenceLabels'] = [static_label]
    if args.gate_plan:
        for plan in load(args.gate_plan):
            ensure(set(plan) <= {'testId', 'expected', 'evidenceLabels', 'required'} and plan['testId'] in plans, 'Unknown or status-setting gate plan')
            ensure(isinstance(plan['evidenceLabels'], list), 'Gate labels must be a list')
            ensure('required' not in plan or isinstance(plan['required'], bool), 'Gate required flag must be boolean and match the approved plan')
            plans[plan['testId']].update(plan)
    gates = []
    for plan in plans.values():
        selected = [raw_by_label[name][1] for name in plan['evidenceLabels'] if name in raw_by_label]
        state = combine([row['status'] for row in selected]) if len(selected) == len(plan['evidenceLabels']) else 'NOT_RUN'
        gates.append({**plan, 'status': state, 'sourceId': source_id,
                      'actual': '由明确映射的本轮证据推导；未映射或证据缺失不计通过', 'time': created})
    gates.append({'testId': 'ARM64-PAGE16384-RUNTIME', 'required': True, 'status': 'BLOCKED', 'sourceId': source_id,
                  'expected': 'ARM64/PAGE_SIZE16384实际安装、启动及JNI', 'actual': '用户已确认暂缺环境；保持门槛，不重复索取环境，不用静态对齐替代。', 'time': created})
    validation = {'stage': '阶段1', 'iteration': args.iteration, 'status': 'FAIL', 'conclusion': '未通过',
                  'sourceId': source_id, 'createdAt': created, 'apks': [{'file': x['file'], 'sha256': x['sha256']} for x in apks],
                  'requiredGates': gates, 'results': final_rows, 'historicalIterations': histories, 'excludedFromCurrent': excluded,
                  'nextStageRecommended': False, 'note': '只有本轮实际匹配证据进入当前结果；门槛由显式审查的计划映射。阶段2/3/4未自动获授权。'}
    deliver['validation.json'] = encoded(validation)
    deliver['evidence-index.json'] = encoded(references)
    counts = collections.Counter(x['status'] for x in final_rows)
    report = [f'湖南校园网 Android 阶段1修订验收报告（{args.iteration}）', f'生成时间：{created}',
              '结论：未通过；不建议自动进入下一阶段。本报告依据已审查输入与实际测试证据生成，脚本生成不等于实机通过。',
              f'版本：{audit["versionName"]} / {audit["versionCode"]}；源码清单SHA256：{source_id}',
              f'当前证据条目统计：{dict(counts)}。条目有重叠，不作为独立实验数或成功率分母。', '',
              '基线与来源：发布副本233文件，原APK仍绑定原始C83清单；一份文档脱敏见source-lineage.json。',
              'source-diff.txt含口令相关语句占位，仅供审查，不保证直接git apply；真实前后SHA见changes.json。', '',
              '设计支持：API26起、targetSdk35；手机双ARM ABI。设计范围不等于已逐台验证范围。',
              '实际已验证范围：仅以validation.json本轮匹配结果的API/ABI/页大小/设备及具体用例为准。',
              '未验证/限制：ARM64 16KB实际运行仍BLOCKED；Doze、8小时自然锁屏和全面厂商生命周期未在本轮完成。',
              '历史迭代的暂停BLOCKED只描述当时修订暂停，不是永久环境缺口；历史通过不转记最终APK通过。', '']
    if args.reviewed_summary:
        summary_path = relative_file(stage, args.reviewed_summary)
        reviewed_summary = summary_path.read_text(encoding='utf-8-sig')
        ensure(reviewed_summary.strip() and len(reviewed_summary) <= 50000 and
               not re.search(r'[A-Za-z]:[\\/]|(?:password|passwd|ticket|token|secret)\s*[:=]\s*\S+', reviewed_summary, re.I),
               'Reviewed summary contains an unexpected absolute path or credential assignment')
        local_reference(summary_path, 'explicitly reviewed final narrative outside Android build inputs')
        report += [reviewed_summary.rstrip(), '']
    report += ['门槛与补充项（required以经审查的已批准计划为准）：']
    report += [f'- {x["testId"]}: {x["status"]}；{"必选" if x["required"] else "补充"}；{x["expected"]}' for x in gates]
    report += ['', '本轮APK（均为既有测试证书，非正式签名）：']
    report += [f'- {x["file"]}: {x["sha256"]}' for x in apks]
    report += ['', 'Lint（原始警告数如实保留）：']
    report += [f'- {x["variant"]}: {x.get("errors", "未统计")}错误 / {x.get("warnings", "未统计")}警告；零警告目标{x.get("zeroWarningTarget", "NOT_RUN")}' for x in audit['lint']]
    report += ['', '用户操作边界：真实登录、注销、修复确认仍由用户手动发起；没有本轮实网证据时不作联网通过结论。',
               '恢复/复现：使用scripts.zip内明确审查过的脚本，先参数化新修订路径，检查显式设备、包名、APK哈希；不清除或卸载主应用。',
               '交付未执行Git提交、GitHub发布或SEALED封存。当前模拟器进程退出尚有无法核实的阻塞，work保持未封存；输出为本轮最终候选交付，阶段验收仍未通过。', '']
    deliver['阶段1验收报告.txt'] = '\n'.join(report).encode('utf-8')
    # Include references added by the separately reviewed final narrative.
    deliver['evidence-index.json'] = encoded(references)
    # Recheck immutable inputs before writing any deliverable. Existing outputs are never overwritten.
    verify_manifest(source, after, check_extras=True)
    for item in apks:
        ensure(sha(OUTPUT / item['file']) == item['sha256'], 'APK changed while preparing delivery')
    for name in deliver:
        destination = assert_stage_write(OUTPUT / name)
        ensure(not destination.exists(), 'Delivery target exists; keep it and review a fresh packaging run')
    sums = {name: hashlib.sha256(data).hexdigest().upper() for name, data in deliver.items()}
    sums.update({x['file']: x['sha256'] for x in apks})
    ensure(not (OUTPUT / 'SHA256SUMS.txt').exists(), 'Existing checksum manifest must not be overwritten')
    if args.validate_only:
        print(json.dumps({'validation': 'PASS', 'mode': 'validate-only', 'stageConclusion': '未通过',
                          'iteration': args.iteration, 'sourceId': source_id, 'preparedFiles': len(deliver) + 1,
                          'resultCount': len(final_rows), 'gateCount': len(gates), 'outputWrites': 0}, ensure_ascii=False))
        return 0
    for name, data in deliver.items():
        destination = assert_stage_write(OUTPUT / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (OUTPUT / 'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name, digest in sorted(sums.items())), encoding='utf-8')
    print(json.dumps({'status': 'FAIL', 'stageConclusion': '未通过', 'iteration': args.iteration,
                      'sourceId': source_id, 'generatedFiles': len(deliver) + 1, 'sealed': False}, ensure_ascii=False))
    return 0  # Packaging succeeded; this is not a stage-acceptance exit code.


if __name__ == '__main__':
    raise SystemExit(main())
