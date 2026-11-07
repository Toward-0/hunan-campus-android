"""Reject mutation of sealed stages or the protected historical trees."""
from pathlib import Path

def require_mutable_stage():
    stage = Path(__file__).resolve().parent
    output = stage.parents[1] / 'outputs' / stage.name
    for name in ['work', 'outputs']:
        protected = Path('D:/codex/2026-11-05/jian') / name
        if stage == protected or stage.is_relative_to(protected):
            raise RuntimeError('Historical evidence is read-only; use a new stage directory')
    if (stage / 'SEALED').exists() or (output / 'SEALED').exists():
        raise RuntimeError('Stage is sealed; create a new revision before writing evidence')
    return stage
