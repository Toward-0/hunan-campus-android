"""Windows emulator process identities; never terminate by name or global ADB state."""
from pathlib import Path
import json, os, re, shutil, subprocess, time

def _psquote(value):return "'"+str(value).replace("'","''")+"'"
def _powershell(script):
    executable=shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    if not executable:raise RuntimeError('Windows process verification unavailable')
    result=subprocess.run([executable,'-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('Windows process identity query failed')
    text=result.stdout.decode('utf-8-sig').strip()
    data=json.loads(text) if text else []
    return data if isinstance(data,list) else [data]

_COMMON=r"""
$ErrorActionPreference='Stop'
function Describe-EmulatorProcess($process) {
 $hasher=[Security.Cryptography.SHA256]::Create()
 try {$digest=([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$process.CommandLine)))).Replace('-','')} finally {$hasher.Dispose()}
 return @{pid=[int]$process.ProcessId;parentPid=[int]$process.ParentProcessId;name=$process.Name;createdUtc=$process.CreationDate.ToUniversalTime().ToString('o');createdTicks=$process.CreationDate.ToUniversalTime().Ticks.ToString();executable=$process.ExecutablePath;commandSha256=$digest}
}
"""
def snapshot_emulator_processes(avd_name,serial,emulator_executable):
    if not re.fullmatch(r's1-json-ui-api(?:26|29|31|33|35|36)',avd_name):raise ValueError('Unexpected revision AVD name')
    match=re.fullmatch(r'emulator-(\d+)',serial)
    if not match:raise ValueError('Explicit emulator serial required')
    port=int(match[1])
    directory=str(Path(emulator_executable).resolve().parent)+'\\'
    avd_pattern=r'(?:-avd\s+)'+avd_name+r'(?:\s|$)'
    port_pattern=r'(?:-port\s+)'+str(port)+r'(?:\s|$)'
    script=_COMMON+"""
$directory=DIR
$rows=@(Get-CimInstance Win32_Process -Filter "Name LIKE 'qemu%' OR Name='emulator.exe'" | Where-Object {
 $_.CommandLine -match AVDPATTERN -and $_.CommandLine -match PORTPATTERN -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($directory,[StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object {Describe-EmulatorProcess $_})
ConvertTo-Json -InputObject $rows -Compress
""".replace('DIR',_psquote(directory)).replace('AVDPATTERN',_psquote(avd_pattern)).replace('PORTPATTERN',_psquote(port_pattern))
    return _powershell(script)

def remaining_recorded_processes(records):
    if not records:return []
    payload=json.dumps(records,separators=(',',':'))
    script=_COMMON+"""
$records=ConvertFrom-Json PAYLOAD
$rows=@(foreach($record in $records){
 $process=Get-CimInstance Win32_Process -Filter ("ProcessId="+[int]$record.pid)
 if($process){$actual=Describe-EmulatorProcess $process;if($actual.createdTicks -eq $record.createdTicks){$actual}}
})
ConvertTo-Json -InputObject $rows -Compress
""".replace('PAYLOAD',_psquote(payload))
    return _powershell(script)

def terminate_verified_processes(records):
    """Recheck PID, parent, creation time, binary and argument hash before CIM Terminate."""
    if not records:return []
    payload=json.dumps(records,separators=(',',':'))
    script=_COMMON+"""
$records=ConvertFrom-Json PAYLOAD
$rows=@(foreach($record in $records){
 $process=Get-CimInstance Win32_Process -Filter ("ProcessId="+[int]$record.pid)
 if(!$process){@{pid=[int]$record.pid;status='PASS';action='already-exited'};continue}
 $actual=Describe-EmulatorProcess $process
 if($actual.parentPid -ne $record.parentPid -or $actual.createdTicks -ne $record.createdTicks -or $actual.executable -ne $record.executable -or $actual.commandSha256 -ne $record.commandSha256 -or $actual.name -ne $record.name){
  @{pid=[int]$record.pid;status='BLOCKED';action='identity-changed-no-termination'};continue
 }
 $terminated=Invoke-CimMethod -InputObject $process -MethodName Terminate -Arguments @{Reason=[uint32]0}
 @{pid=[int]$record.pid;status=if($terminated.ReturnValue -eq 0){'PASS'}else{'BLOCKED'};action='terminate-exact-reviewed-process';returnValue=[int]$terminated.ReturnValue}
})
ConvertTo-Json -InputObject $rows -Compress
""".replace('PAYLOAD',_psquote(payload))
    return _powershell(script)

def wait_recorded_processes_exit(records,timeout=15):
    end=time.monotonic()+timeout
    while True:
        remaining=remaining_recorded_processes(records)
        if not remaining:return {'status':'PASS','recordedPids':[int(x['pid']) for x in records],'remainingPids':[]}
        if time.monotonic()>=end:return {'status':'BLOCKED','recordedPids':[int(x['pid']) for x in records],'remainingPids':[int(x['pid']) for x in remaining]}
        time.sleep(1)
