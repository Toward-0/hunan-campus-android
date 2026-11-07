"""Read-only verification of the reviewed handoff; never runs Android tools."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

count = 0
for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    expected, name = line.split('  ', 1)
    target = (root/name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise SystemExit('Missing or unsafe path: '+name)
    if digest(target) != expected:
        raise SystemExit('SHA256 mismatch: '+name)
    count += 1

manifest = json.loads((root/'evidence/source-manifest.json').read_text(encoding='utf-8-sig'))
assert len(manifest) == 233
for item in manifest:
    assert digest(root/'source'/item['path']) == item['sha256'], item['path']

original = root/'evidence/original-source-manifest.json'
assert digest(original) == 'C83DFEAB98CBBA964C53000D9C01B300E98F706DBFBD2D376E0DAB6117F77DEA'
binding = json.loads((root/'evidence/original-build-binding.json').read_text(encoding='utf-8-sig'))
for apk in binding['apks']:
    kind = 'main' if '-candidate-' in apk['file'] else 'isolation'
    assert digest(root/'artifacts'/kind/apk['file']) == apk['sha256']
print(json.dumps({'status':'PASS','filesVerified':count,'sourceFiles':len(manifest),'apksVerified':len(binding['apks']),'androidTestsRun':False}))
