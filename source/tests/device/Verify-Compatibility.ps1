#requires -Version 7.0
param(
 [Parameter(Mandatory)][string]$Adb,
 [Parameter(Mandatory)][string]$Aapt,
 [Parameter(Mandatory)][string]$Serial,
 [Parameter(Mandatory)][ValidateSet('org.esurfing.hunan.isolation')][string]$Package,
 [Parameter(Mandatory)][string]$Apk,
 [Parameter(Mandatory)][string]$EvidenceDirectory,
 [ValidateSet('Environment','Install','JNI','Internet','Repair','UI','Stop')][string]$Action='Environment',
 [int]$TimeoutSeconds=480
)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../../stage-env.ps1"
if($TimeoutSeconds -lt 10 -or $TimeoutSeconds -gt 900){throw 'Timeout must be 10..900 seconds'}
$Adb=(Resolve-Path -LiteralPath $Adb).Path
$Aapt=(Resolve-Path -LiteralPath $Aapt).Path
$Apk=(Resolve-Path -LiteralPath $Apk).Path
$EvidenceDirectory=[IO.Path]::GetFullPath($EvidenceDirectory)
$allowedEvidence=[IO.Path]::GetFullPath((Join-Path $StageRoot 'evidence')).TrimEnd('\')
if($EvidenceDirectory -ne $allowedEvidence -and !$EvidenceDirectory.StartsWith($allowedEvidence+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'EvidenceDirectory must stay inside the current stage evidence directory'}
New-Item -ItemType Directory -Force -Path $EvidenceDirectory|Out-Null
$commands=[Collections.Generic.List[object]]::new()
function Invoke-AdbTimed([string[]]$Arguments,[int]$Seconds=30) {
 $start=[Diagnostics.ProcessStartInfo]::new($Adb)
 $start.UseShellExecute=$false;$start.CreateNoWindow=$true
 $start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
 foreach($arg in @('-s',$Serial)+$Arguments){$start.ArgumentList.Add($arg)}
 $proc=[Diagnostics.Process]::new();$proc.StartInfo=$start
 if(!$proc.Start()){throw 'Unable to start adb'}
 $stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync()
 if(!$proc.WaitForExit($Seconds*1000)){$proc.Kill($true);throw "ADB timeout after $Seconds seconds"}
 $text=$stdout.GetAwaiter().GetResult();$errorText=$stderr.GetAwaiter().GetResult()
 $commands.Add(@{arguments=$Arguments;exitCode=$proc.ExitCode})
 if($proc.ExitCode -ne 0){throw "ADB exit $($proc.ExitCode): $errorText"}
 return $text
}
$row=@{time=(Get-Date).ToString('o');serial=$Serial;package=$Package;apk=(Split-Path $Apk -Leaf);apkSha256=(Get-FileHash -LiteralPath $Apk -Algorithm SHA256).Hash;action=$Action;status='NOT_RUN'}
try {
 $apkInfo=& $Aapt dump badging $Apk
 if($LASTEXITCODE -ne 0 -or !($apkInfo -match "^package: name='org.esurfing.hunan.isolation' ")){throw 'APK must be the separate isolation package'}
 if((Invoke-AdbTimed @('get-state')).Trim() -ne 'device'){throw 'Device is unavailable or unauthorized'}
 $properties=@{}
 foreach($name in @('ro.product.manufacturer','ro.product.model','ro.build.version.sdk','ro.build.version.release','ro.product.cpu.abilist','ro.product.cpu.abilist32','ro.product.cpu.abilist64')){$properties[$name]=(Invoke-AdbTimed @('shell','getprop',$name)).Trim()}
 $row.environment=$properties;$row.pageSize=(Invoke-AdbTimed @('shell','getconf','PAGE_SIZE')).Trim()
 $nativeLine=($apkInfo|Where-Object{$_ -match '^native-code:'}) -join ''
 $apkAbis=@([regex]::Matches($nativeLine,"'([^']+)'" )|ForEach-Object{$_.Groups[1].Value})
 $deviceAbis=$properties['ro.product.cpu.abilist'].Split(',')
 if(!($apkAbis|Where-Object{$_ -in $deviceAbis})){throw 'Device supported ABIs do not match this APK'}
 $row.apkAbis=$apkAbis
 if($Action -eq 'Install'){
  $result=Invoke-AdbTimed @('install','-r',$Apk) $TimeoutSeconds
  if($result -notmatch 'Success'){throw 'Package installation did not report Success'}
 }
 if($Action -ne 'Environment'){
  $installed=(Invoke-AdbTimed @('shell','pm','path',$Package)).Trim().Replace('package:','')
  if($installed -notmatch '^/data/app/[^\s]+\.apk$'){throw 'Unexpected installed APK path'}
  $actual=(Invoke-AdbTimed @('shell','sha256sum',$installed)).Split(' ',[StringSplitOptions]::RemoveEmptyEntries)[0]
  if($actual -ne $row.apkSha256){throw 'Installed APK hash does not match explicit APK'}
  $row.installedHashMatched=$true
 }
 $probe=switch($Action){JNI{'CompatProbe'} Internet{'InternetProbe'} Repair{'StabilityProbe'} UI{'UiProbe'} default{$null}}
 if($probe){
  $argsList=@('shell','am','instrument','-w','-r')
  if($Action -eq 'Repair'){$argsList+=@('-e','mode','repair')}
  $argsList+="$Package/org.esurfing.hunan.$probe"
  $result=Invoke-AdbTimed $argsList $TimeoutSeconds
  $result|Set-Content (Join-Path $EvidenceDirectory "$Action-instrumentation.txt") -Encoding utf8
  if($result -notmatch 'INSTRUMENTATION_CODE: -1' -or $result -match 'FAIL|Process crashed'){throw 'Instrumentation did not pass'}
  if($Action -eq 'JNI'){
   $jni=Invoke-AdbTimed @('shell','run-as',$Package,'cat','files/compat-jni.json')
   $jni|Set-Content (Join-Path $EvidenceDirectory 'jni.json') -Encoding utf8
   if(($jni|ConvertFrom-Json).status -ne 'PASS'){throw 'JNI result did not pass'}
  }
 }
 if($Action -eq 'Stop'){Invoke-AdbTimed @('shell','am','force-stop',$Package)|Out-Null}
 $row.status='PASS'
} catch {$row.status='FAIL';$row.error=$_.Exception.Message;Write-Warning $row.error}
finally {
 if($Action -in @('JNI','Internet','Repair','UI','Stop')){try{Invoke-AdbTimed @('shell','am','force-stop',$Package)|Out-Null}catch{$row.cleanupError=$_.Exception.Message;$row.status='FAIL'}}
 $row.commands=$commands
 $row|ConvertTo-Json -Depth 8|Set-Content (Join-Path $EvidenceDirectory "$Action-result.json") -Encoding utf8
}
if($row.status -ne 'PASS'){exit 1}
