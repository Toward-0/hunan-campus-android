param([string]$StageRoot=(Split-Path $PSScriptRoot -Parent),[string]$ToolsConfig)
$ErrorActionPreference='Stop'
$StageRoot=[IO.Path]::GetFullPath($StageRoot).TrimEnd('\','/')
$scriptStage=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent)).TrimEnd('\','/')
if($StageRoot -ne $scriptStage){throw 'StageRoot must match this source copy'}
if(!$ToolsConfig){$ToolsConfig=Join-Path $StageRoot 'tools.local.json'}
function Assert-NoReparseAncestor([string]$Path) {
 $current=[IO.Path]::GetFullPath($Path)
 while($current) {
  if(Test-Path -LiteralPath $current) {
   $item=Get-Item -LiteralPath $current -Force
   if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw "Reparse point not allowed for writes: $current"}
   if($item.PSIsContainer -and ((Test-Path -LiteralPath (Join-Path $current 'SEALED')) -or (Test-Path -LiteralPath (Join-Path $current 'SEALED.json')))){throw "Sealed ancestor: $current"}
  }
  $parent=Split-Path $current -Parent
  if(!$parent -or $parent -eq $current){break}
  $current=$parent
 }
}
function Test-PathWithin([string]$Path,[string]$Root) {
 $p=[IO.Path]::GetFullPath($Path).TrimEnd('\','/')
 $r=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
 return $p.Equals($r,[StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith($r+'\',[StringComparison]::OrdinalIgnoreCase)
}
Assert-NoReparseAncestor $StageRoot
if(!(Test-PathWithin $ToolsConfig $StageRoot)){throw 'ToolsConfig must be local to this stage'}
Assert-NoReparseAncestor $ToolsConfig
$StageTools=Get-Content -LiteralPath $ToolsConfig -Raw -Encoding UTF8|ConvertFrom-Json
foreach($property in @('JdkHome','GradleExecutable','AndroidSdk','EmulatorExecutable','TestKeystore','SigningPasswordVariable','OutputRoot','ProtectedRoots')) {
 if(!$StageTools.$property){throw "Missing local tool configuration: $property"}
}
$StageOutputRoot=[IO.Path]::GetFullPath($StageTools.OutputRoot).TrimEnd('\','/')
if($StageOutputRoot -eq $StageRoot){throw 'Output directory must be separate from working copy'}
function Assert-StageWritePath([string]$Path) {
 $p=[IO.Path]::GetFullPath($Path)
 foreach($protected in $StageTools.ProtectedRoots) {
  if(Test-PathWithin $p $protected){throw "Historical path is read-only: $p"}
 }
 if(!(Test-PathWithin $p $StageRoot) -and !(Test-PathWithin $p $StageOutputRoot)){throw "Write outside current stage/output: $p"}
 Assert-NoReparseAncestor $p
 return $p
}
$null=Assert-StageWritePath $StageRoot
$null=Assert-StageWritePath $StageOutputRoot
if(!(Test-PathWithin $StageTools.AndroidSdk $StageRoot)){throw 'Build SDK must be a private current-stage copy'}
foreach($p in @((Join-Path $StageTools.JdkHome 'bin/java.exe'),$StageTools.GradleExecutable,$StageTools.EmulatorExecutable,$StageTools.TestKeystore)) {
 if(!(Test-Path -LiteralPath $p -PathType Leaf)){throw 'Required local tool/signing file missing'}
}
if(!(Test-Path -LiteralPath $StageTools.AndroidSdk -PathType Container)){throw 'Private build SDK missing'}
$env:JAVA_HOME=$StageTools.JdkHome
$env:GRADLE_USER_HOME=Join-Path $StageRoot 'gradle-user'
$env:ANDROID_HOME=$StageTools.AndroidSdk
$env:ANDROID_SDK_ROOT=$env:ANDROID_HOME
$env:ANDROID_USER_HOME=Join-Path $StageRoot 'android-user'
$env:ANDROID_EMULATOR_HOME=$env:ANDROID_USER_HOME
$env:ANDROID_PREFS_ROOT=$null
$env:ANDROID_SDK_HOME=$null
$env:USERPROFILE=Join-Path $StageRoot 'java-user'
$env:LOCALAPPDATA=Join-Path $StageRoot 'local-appdata'
$env:APPDATA=Join-Path $StageRoot 'appdata'
$env:ANDROID_AVD_HOME=Join-Path $StageRoot 'avd'
$env:TEMP=Join-Path $StageRoot 'tmp'
$env:TMP=$env:TEMP
$env:JAVA_TOOL_OPTIONS=('-XX:-UsePerfData -Djava.io.tmpdir="{0}" -Djdk.net.unixdomain.tmpdir="{0}" -Duser.home="{1}" -XX:ErrorFile="{2}/tmp/hs_err_pid%p.log"' -f $env:TEMP,$env:USERPROFILE,$StageRoot)
$env:PYTHONDONTWRITEBYTECODE='1'
$env:HUNAN_EXTERNAL_SIGNING='1'
foreach($p in @($env:GRADLE_USER_HOME,$env:ANDROID_HOME,$env:ANDROID_USER_HOME,$env:ANDROID_AVD_HOME,$env:USERPROFILE,$env:LOCALAPPDATA,$env:APPDATA,$env:TEMP,(Join-Path $StageRoot 'cxx'),(Join-Path $StageRoot 'gradle-project'),(Join-Path $StageRoot 'evidence'),(Join-Path $StageRoot 'pack'),$StageOutputRoot)) {
 $p=Assert-StageWritePath $p
 New-Item -ItemType Directory -Force -Path $p|Out-Null
}
