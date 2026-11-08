"""Bind explicit completed visual decisions to original screenshots; never infer a review."""
from pathlib import Path
from stage_guard import require_mutable_stage, assert_stage_write
import argparse, datetime, hashlib, json, re

p = argparse.ArgumentParser()
p.add_argument('--iteration', required=True)
p.add_argument('--api', type=int, required=True)
p.add_argument('--decisions', required=True)
p.add_argument('--source-id', required=True)
p.add_argument('--apk-sha256', required=True)
p.add_argument('--environment-label', help='Explicit apiNN or realmeNN label; API still checked from each result')
p.add_argument('--review-limit', default='')
a = p.parse_args()
stage = require_mutable_stage()
assert re.fullmatch(r'r[1-9][0-9]*', a.iteration)
environment_label = a.environment_label or ('api' + str(a.api))
assert re.fullmatch(r'(api|realme)' + str(a.api), environment_label)
decision_path = (stage / a.decisions).resolve()
assert decision_path.is_relative_to(stage / 'evidence')
decisions = json.loads(decision_path.read_text(encoding='utf-8-sig'))
states = {'PASS', 'FAIL', 'NOT_RUN', 'BLOCKED'}
titles = ['连接', '账号', '诊断', '更多']
screens = []; children = []; all_states = []
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()
for label, decision in decisions.items():
    suffix = r'-ui-font[12]-(current|gesture|three)' + (r'-none' if environment_label.startswith('api') else '')
    assert re.fullmatch(a.iteration + '-' + environment_label + suffix, label)
    result_path = stage / 'evidence' / label / 'result.json'
    raw = json.loads(result_path.read_text(encoding='utf-8-sig'))
    assert raw['sourceId'] == a.source_id and raw['apkSha256'] == a.apk_sha256
    assert int(raw['api']) == a.api and raw['package'] == 'org.esurfing.hunan.isolation'
    captured = raw['result']['screens']
    assert len(captured) == 15 and len(decision['names']) == 15
    assert set(decision['names']) == {s['name'] for s in captured}
    assert all(decision[k] in states for k in ('identity', 'app', 'system'))
    per_screen = decision.get('perScreen', {})
    assert set(per_screen) <= set(decision['names'])
    assert all(set(item) <= {'identity', 'app', 'system', 'observation'} for item in per_screen.values())
    children.append({'path': result_path.relative_to(stage).as_posix(), 'sha256': sha(result_path),
                     'sourceId': raw['sourceId'], 'apkSha256': raw['apkSha256']})
    for original in captured:
        path = result_path.parent / (original['name'] + '.png')
        assert path.resolve().is_relative_to(result_path.parent.resolve())
        item_decision = dict(decision)
        item_decision.update(per_screen.get(original['name'], {}))
        assert all(item_decision[k] in states for k in ('identity', 'app', 'system'))
        assert sha(path) == original['sha256'].upper()
        assert titles[original['pageIndex']] == original['pageTitle']
        assert original['foregroundPackage'] == raw['package'] and isinstance(original['windowId'], int)
        review = {'evidence': path.relative_to(stage).as_posix(), 'sha256': sha(path),
                  'pageIndex': original['pageIndex'], 'pageTitle': original['pageTitle'],
                  'windowId': original['windowId'], 'foregroundPackage': original['foregroundPackage'],
                  'identityStatus': item_decision['identity'], 'appControlVisualStatus': item_decision['app'],
                  'systemStatusBarVisualStatus': item_decision['system'], 'observation': item_decision['observation']}
        if original['name'] == 'dropdown':
            review['manualTextLayoutStatus'] = item_decision['app']
        screens.append(review)
        all_states.extend(item_decision[k] for k in ('identity', 'app', 'system'))
state = next((x for x in ('FAIL', 'BLOCKED', 'NOT_RUN') if x in all_states), 'PASS')
label = a.iteration + '-' + environment_label + '-visual'
result = {'kind': 'ui-visual-review', 'label': label, 'iteration': a.iteration,
          'sourceId': a.source_id, 'apkSha256': a.apk_sha256, 'status': state,
          'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'reviewMethod': '逐张打开全部原始PNG人工检查，再核对每图SHA256、页码、页面标题、前台包和窗口绑定；自动测试PASS不替代视觉检查。',
          'limit': '滚动视口可以裁去非当前目标内容；关键按钮和输入框分别滚到安全区核查。单行可滚动输入内容不要求同屏全文，固定标签与说明必须可读。' + a.review_limit,
          'children': children, 'screens': screens}
target = stage / 'evidence' / (label + '.json')
assert_stage_write(target)
assert not target.exists()
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'label': label, 'screensReviewed': len(screens), 'status': state}))
