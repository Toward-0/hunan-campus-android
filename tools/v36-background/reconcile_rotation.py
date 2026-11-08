"""Reconcile an existing observation using already-whitelisted rotated timing rows."""
import datetime
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).parent / 'evidence'
names = {
    'original': 'v36-realme-oem-allowed-short.json',
    'start': 'v36-realme-oem-allowed-short-start.json',
    'end': 'v36-realme-oem-allowed-short-end.json',
    'supplement': 'v36-realme-rotation-supplement.json',
}
data = {k: json.loads((root / v).read_text(encoding='utf8')) for k, v in names.items()}

def rows(snapshot):
    timing = next(q['value'] for q in snapshot['queries'] if q['query'] == 'timing' and q['exitCode'] == 0)
    return [{k: json.loads(v) for k, v in re.findall(r'"([A-Za-z]+)":("[A-Z_]+"|[0-9]+|true|false)', line)} for line in timing.splitlines()]

original = data['original']
start, end = original['startEvent'], original['endEvent']
first_elapsed = max(r['elapsed'] for r in rows(data['start']))
last_elapsed = max(r['elapsed'] for r in rows(data['end']))
window = [r for r in rows(data['supplement']) if r.get('generation') == int(start[1]) and first_elapsed < r.get('elapsed', 0) <= last_elapsed]
deliveries = [r for r in window if r.get('point') in ('TIMER_DELIVERY', 'ALARM_DELIVERY')]
checks = {
    'sameAuthenticatedGeneration': start[1] == end[1] and start[2] == end[2] == 'AUTHENTICATED',
    'newSuccessfulHeartbeat': start[4] == end[4] == 'PASS' and int(end[3]) > int(start[3]),
    'newSuccessfulInternet': start[6] == end[6] == 'PASS' and int(end[5]) > int(start[5]),
    'screenOffHeartbeatDelivery': any(r.get('kind') == 'HEARTBEAT' and r.get('interactive') is False for r in deliveries),
    'screenOffInternetDelivery': any(r.get('kind') == 'INTERNET' and r.get('interactive') is False for r in deliveries),
    'screenOffHeartbeatFinished': any(r.get('kind') == 'HEARTBEAT' and r.get('point') == 'FINISH' and r.get('interactive') is False for r in window),
    'screenOffInternetFinished': any(r.get('kind') == 'INTERNET' and r.get('point') == 'FINISH' and r.get('interactive') is False for r in window),
    'noTimingErrors': bool(window) and all(r.get('error') == 'NONE' for r in window),
}
report = {
    'testId': 'REAL-NETWORK-SHORT-ROTATION-RECONCILIATION',
    'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'PASS' if all(checks.values()) else 'FAIL',
    'apkSha256': original['apkSha256'],
    'package': original['package'],
    'observationStart': original['time'],
    'durationSeconds': original['durationSeconds'],
    'automaticAuthRequests': 0,
    'additionalNetworkProbes': 0,
    'originalCollectorStatus': original['status'],
    'reason': 'Original collector read only current trace.jsonl; heartbeat delivery had moved to trace.previous.jsonl. Reconcile only the original observation window using both files; original FAIL is preserved unchanged.',
    'observation': 'USB connected; normal screen-off, not forced idle. Existing manually established session; no reconnect.',
    'elapsedWindowExclusiveStartInclusiveEnd': [first_elapsed, last_elapsed],
    'startEvent': start,
    'endEvent': end,
    'checks': checks,
    'deliveries': deliveries,
    'deliveryLatenessMs': {r['kind']: r['elapsed'] - r['dueElapsed'] for r in deliveries},
    'successfulHeartbeatTimestampAdvanceMs': int(end[3]) - int(start[3]),
    'successfulInternetTimestampAdvanceMs': int(end[5]) - int(start[5]),
    'inputs': [{'file': v, 'sha256': hashlib.sha256((root / v).read_bytes()).hexdigest().upper()} for v in names.values()],
    'limitations': ['One 311.81 second normal lockscreen observation with USB power.', 'No eight-hour endurance or unplugged physical-device Doze validation.', 'No other physical phone brand tested.'],
}
dest = root / 'v36-realme-oem-allowed-reconciled.json'
assert not dest.exists(), 'Do not overwrite existing evidence'
dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(report, ensure_ascii=False, indent=2))
