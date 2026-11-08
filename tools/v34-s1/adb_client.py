"""Local ADB smart socket, shell v2 exit status and sync. No server/key writes."""
import socket, struct, pathlib, argparse, time
def read(s,n):
    b=b''
    while len(b)<n:
        v=s.recv(n-len(b))
        if not v: raise EOFError('ADB closed connection')
        b+=v
    return b
def request(s,cmd):
    b=cmd.encode(); s.sendall(f'{len(b):04x}'.encode()+b)
    if read(s,4)!=b'OKAY': raise RuntimeError(read(s,int(read(s,4),16)).decode(errors='replace'))
def connect(serial=None,timeout=30):
    s=socket.create_connection(('127.0.0.1',5037),5); s.settimeout(timeout)
    if serial: request(s,'host:transport:'+serial)
    return s
def devices():
    with connect() as s:
        request(s,'host:devices-l'); return read(s,int(read(s,4),16)).decode()
def shell(serial,cmd,timeout=60):
    with connect(serial,timeout) as s:
        request(s,'shell,v2,raw:'+cmd); out=b''; err=b''; deadline=time.monotonic()+timeout
        while True:
            s.settimeout(max(.1,deadline-time.monotonic()))
            ident,n=struct.unpack('<BI',read(s,5)); b=read(s,n)
            if ident==1: out+=b
            elif ident==2: err+=b
            elif ident==3: return (b[0] if len(b)==1 else int.from_bytes(b,'little')),out,err
def push(serial,local,remote):
    if not remote.startswith('/data/local/tmp/campus-s1-'): raise ValueError('Remote path outside stage scope')
    with connect(serial,60) as s:
        request(s,'sync:'); path=(remote+',33200').encode(); s.sendall(b'SEND'+struct.pack('<I',len(path))+path)
        with open(local,'rb') as f:
            while b:=f.read(65536): s.sendall(b'DATA'+struct.pack('<I',len(b))+b)
        s.sendall(b'DONE'+struct.pack('<I',int(time.time())))
        ident=read(s,4); n=int.from_bytes(read(s,4),'little')
        if ident!=b'OKAY': raise RuntimeError(read(s,n).decode())
class PageSizeUnavailable(RuntimeError):
    def __init__(self, attempts):
        super().__init__('Exact page size is unavailable from reviewed read-only queries')
        self.attempts=attempts

def query_page_size(serial,timeout=10):
    """Return actual bytes; select AT_PAGESZ on-device if old getconf is absent."""
    if not serial:raise ValueError('Explicit serial required for page-size query')
    # od reads its own auxv. Shell builtins emit ONLY the AT_PAGESZ value;
    # neither addresses nor other auxiliary-vector entries cross ADB.
    queries=[
        ('getconf-PAGE_SIZE','getconf PAGE_SIZE'),
        ('getconf-PAGESIZE','getconf PAGESIZE'),
        ('auxv-AT_PAGESZ-u64','set -o pipefail; od -An -tu8 /proc/self/auxv | while read -r kind value; do if [ "$kind" = 6 ] && [ "$value" -gt 0 ] 2>/dev/null; then echo "$value"; fi; done'),
        ('auxv-AT_PAGESZ-u32','set -o pipefail; od -An -tu4 /proc/self/auxv | while read -r kind value kind2 value2; do if [ "$kind" = 6 ] && [ "$value" -gt 0 ] 2>/dev/null; then echo "$value"; fi; if [ "$kind2" = 6 ] && [ "$value2" -gt 0 ] 2>/dev/null; then echo "$value2"; fi; done'),
    ]
    attempts=[]
    for name,command in queries:
        row={'query':name}
        try:
            code,out,err=shell(serial,command,timeout)
            row['exitCode']=code
            text=out.decode('ascii',errors='replace').strip()
            value=int(text) if text.isascii() and text.isdigit() and len(text)<=8 else None
            valid=code==0 and value is not None and 1024<=value<=1048576 and value&(value-1)==0
            if valid:
                row.update(valueBytes=value,status='PASS');attempts.append(row)
                return {'pageSize':value,'method':name,'attempts':attempts}
            denied=b'Permission denied' in err or b'permission denied' in err
            row.update(status='FAIL',failureKind='permission-denied' if denied else 'nonzero-exit' if code else 'invalid-value')
            attempts.append(row)
            if denied:break
        except (OSError,EOFError,RuntimeError) as error:
            row.update(status='FAIL',failureKind=type(error).__name__);attempts.append(row)
            break
    raise PageSizeUnavailable(attempts)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--serial');p.add_argument('--timeout',type=int,default=60);p.add_argument('--out');p.add_argument('command',choices=['devices','shell','push']);p.add_argument('args',nargs='*');a=p.parse_args()
    if a.command=='devices': print(devices())
    elif a.command=='push': push(a.serial,*a.args)
    else:
        if not a.serial: p.error('--serial required')
        code,out,err=shell(a.serial,' '.join(a.args),a.timeout)
        if a.out: pathlib.Path(a.out).write_bytes(out)
        else: print(out.decode(errors='replace'),end='')
        if err: print(err.decode(errors='replace'))
        raise SystemExit(code)
