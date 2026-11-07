"""Generate public fixture key material; never reads any device or captured module."""
import lzma
import struct
from pathlib import Path

MASK = 0xffffffff
DELTA = 0x61c88647
WRAP = b'Rirn53a;feb#UXES5ZrRBTGmYwml:fRt'  # upstream format constant, not a session secret

def encrypt(block, key):
    v0, v1 = struct.unpack('<2I', block)
    k = struct.unpack('<4I', key)
    total = 0
    for _ in range(32):
        v0 = (v0 + k[total & 3] + (v1 ^ total) + ((v1 << 4) ^ (v1 >> 5))) & MASK
        total = (total - DELTA) & MASK
        v1 = (v1 + ((v0 << 4) ^ (v0 >> 5)) + k[(total >> 11) & 3] + (v0 ^ total)) & MASK
    return struct.pack('<2I', v0, v1)

def wrap(data):
    alone = lzma.compress(data, format=lzma.FORMAT_ALONE)
    raw = alone[13:]
    padding = 8 - len(raw) % 8
    raw += bytes([padding]) * padding
    wire = b''.join(encrypt(encrypt(raw[i:i+8], WRAP[16:]), WRAP[:16]) for i in range(0, len(raw), 8))
    return b'001\x00\x24' + b'00000000-0000-0000-0000-000000000005' + alone[:5] + struct.pack('<I', 0x20000000 | len(data)) + wire

out = Path(__file__).resolve().parents[1] / 'app/src/isolation/assets'
out.mkdir(parents=True, exist_ok=True)
header = bytearray(0x103)
header[0xff], header[0xfc], header[0xfa] = 0x10, 48, 0
header[0x11:0x11+48] = bytes(range(48))
data = bytes(header) + b'var codex=5; function e(v){return cdy(codex,0,cdckey,cdciv,v);}'
(out / 'synthetic-module.zsm').write_bytes(wrap(data))
(out / 'synthetic-short.zsm').write_bytes(wrap(b'bad'))
for code in range(1, 10):
    (out / f'synthetic-type-{code}.zsm').write_bytes(wrap(bytes(header) + f'var codex={code}; function e(v){{return cdy(codex,0,cdckey,cdciv,v);}}'.encode()))
print('Generated valid and malformed public synthetic modules; no captured data used.')
