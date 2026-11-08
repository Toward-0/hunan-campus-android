"""Revision-local writes; reject sealed roots, ancestors, and reparse points."""
from pathlib import Path
import os
import stat

# Keep lexical paths until reparse checks finish: resolving both actual/expected
# first would let a replaced revision-root junction redirect both comparisons.
STAGE = Path(os.path.abspath(__file__)).parent
EXPECTED = Path('D:/codex/2026-11-08/android-apk-4-1-2026-11/work/s1-json-ui-20261108-01')
OUTPUT = EXPECTED.parent.parent / 'outputs' / EXPECTED.name
PROTECTED = tuple(Path(p) for p in (
    'D:/codex/2026-11-05/jian/work',
    'D:/codex/2026-11-05/jian/outputs',
    'D:/codex/2026-11-06/d-codex-2026-11-05-jian-3/work',
    'D:/codex/2026-11-06/d-codex-2026-11-05-jian-3/outputs',
    'D:/codex/2026-10-30/ke-y/work/toolchain',
))

def assert_stage_write(path):
    p = Path(os.path.abspath(path))
    if any(p == old or p.is_relative_to(old) for old in PROTECTED):
        raise RuntimeError('Historical path is read-only')
    if not any(p == root or p.is_relative_to(root) for root in (EXPECTED, OUTPUT)):
        raise RuntimeError('Writable path escapes this revision')
    for part in (p, *p.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Reparse points are not writable revision paths')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise RuntimeError('Hardlinked files are not writable revision outputs')
        if stat.S_ISDIR(info.st_mode) and any((part/name).exists() for name in ('SEALED','SEALED.json')):
            raise RuntimeError('Sealed ancestor: prepare a new revision')
    return p

def require_mutable_stage():
    if STAGE != EXPECTED:
        raise RuntimeError('Use this revision at its reviewed stage root')
    for root in (STAGE, OUTPUT):
        assert_stage_write(root)
    for name in ('evidence','tmp','avd','android-user','java-user','appdata','local-appdata'):
        p = assert_stage_write(STAGE/name)
        p.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(STAGE/'tmp'), TMP=str(STAGE/'tmp'),
        PYTHONDONTWRITEBYTECODE='1')
    return STAGE
