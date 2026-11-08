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

current = json.loads((root/'CURRENT_DELIVERY.json').read_text(encoding='utf-8-sig'))
delivery = (root/current['delivery']).resolve()
assert delivery.is_relative_to(root)
manifest_path = delivery/'source-manifest.json'
assert digest(manifest_path) == current['sourceManifestSha256']
manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
assert manifest['versionCode'] == current['versionCode']
for item in manifest['files']:
    assert digest(root/'source'/item['path']) == item['sha256'], item['path']

validation = json.loads((delivery/'validation.json').read_text(encoding='utf-8-sig'))
assert validation['binding']['versionCode'] == current['versionCode']
for apk in validation['binding']['apks']:
    assert digest(delivery/apk['file']) == apk['sha256'], apk['file']
main_apks = [apk for apk in validation['binding']['apks'] if '-candidate-phone.apk' in apk['file']]
assert len(main_apks) == 1 and main_apks[0]['sha256'] == current['mainApkSha256']

original = root/'evidence/original-source-manifest.json'
assert digest(original) == 'C83DFEAB98CBBA964C53000D9C01B300E98F706DBFBD2D376E0DAB6117F77DEA'
binding = json.loads((root/'evidence/original-build-binding.json').read_text(encoding='utf-8-sig'))
for apk in binding['apks']:
    kind = 'main' if '-candidate-' in apk['file'] else 'isolation'
    assert digest(root/'artifacts'/kind/apk['file']) == apk['sha256']
print(json.dumps({'status':'PASS','filesVerified':count,'versionCode':current['versionCode'],
                  'sourceFiles':len(manifest['files']),'currentApksVerified':len(validation['binding']['apks']),
                  'historicalApksVerified':len(binding['apks']),'androidTestsRun':False}))
