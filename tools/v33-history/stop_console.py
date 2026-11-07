"""Graceful console shutdown of an owned AVD; no host process-tree privilege needed."""
from pathlib import Path
from stage_guard import require_mutable_stage
require_mutable_stage()
from adb_client import shell,devices
import socket,re,json,argparse,time,datetime
R=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--api',required=True,type=int);a=p.parse_args()
boot=json.loads((R/f'evidence/emulator-api{a.api}-boot.json').read_text(encoding='utf-8'))
assert Path(boot['avd']).is_relative_to(R/'avd')
serial=boot['serial'];assert re.fullmatch(r'emulator-\d+',serial)
port=int(serial.split('-')[1]);assert port in range(5554,5568,2)
c,b,e=shell(serial,'getprop ro.kernel.qemu',10);assert c==0 and b.strip()==b'1'
row={'api':a.api,'serial':serial,'avd':boot['avd'],'time':datetime.datetime.now().astimezone().isoformat()}
def receive(s):
    result=b''
    while not result.endswith(b'OK\r\n') and not result.endswith(b'OK\n'):
        part=s.recv(4096)
        if not part:break
        result+=part
        if b'KO:' in result:break
        assert len(result)<16384
    return result.decode()
with socket.create_connection(('127.0.0.1',port),timeout=10) as s:
    banner=receive(s)
    if 'Authentication required' in banner:
        match=re.search(r"'([^']*\.emulator_console_auth_token)'",banner);assert match,'Auth token path not recognized'
        tokenpath=Path(match.group(1));row['tokenPath']=str(tokenpath)
        # Read only the management token advertised by the verified own emulator. Never export its contents.
        token=tokenpath.read_text(encoding='utf-8-sig').strip();assert re.fullmatch('[A-Za-z0-9+/=_-]{1,256}',token)
        s.sendall(('auth '+token+'\n').encode());assert 'OK' in receive(s)
    s.sendall(b'kill\n');row['consoleResult']=receive(s).strip()
end=time.monotonic()+30
while time.monotonic()<end:
    if not any(line.split()[0]==serial for line in devices().splitlines() if line.strip()):break
    time.sleep(1)
else:raise TimeoutError('Emulator still connected')
row['status']='PASS';(R/f'evidence/console-cleanup-api{a.api}.json').write_text(json.dumps(row,indent=2),encoding='utf-8');print(json.dumps(row))
