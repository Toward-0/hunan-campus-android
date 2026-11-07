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
