param([string]$StageRoot=(Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference='Stop'
$StageRoot=[IO.Path]::GetFullPath($StageRoot)
foreach($protected in @('D:/codex/2026-11-05/jian/work','D:/codex/2026-11-05/jian/outputs')) {
 $protected=[IO.Path]::GetFullPath($protected).TrimEnd('\')
 if($StageRoot -eq $protected -or $StageRoot.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Historical directory is read-only'}
}
if(Test-Path -LiteralPath (Join-Path $StageRoot 'SEALED')){throw 'Stage is sealed; create a new stage copy'}
$env:JAVA_HOME='D:/codex/2026-10-30/ke-y/work/toolchain/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64'
$env:GRADLE_USER_HOME=Join-Path $StageRoot 'gradle-user'
$env:ANDROID_HOME=Join-Path $StageRoot 'sdk'
$env:ANDROID_SDK_ROOT=$env:ANDROID_HOME
$env:ANDROID_USER_HOME=Join-Path $StageRoot 'android-user'
$env:ANDROID_EMULATOR_HOME=$env:ANDROID_USER_HOME
# AGP rejects conflicting old and current preference-location variables.
# ANDROID_USER_HOME is the single build-side preference root.
$env:ANDROID_PREFS_ROOT=$null
$env:ANDROID_SDK_HOME=$null
$env:USERPROFILE=Join-Path $StageRoot 'java-user'
$env:LOCALAPPDATA=Join-Path $StageRoot 'local-appdata'
$env:APPDATA=Join-Path $StageRoot 'appdata'
$env:ANDROID_AVD_HOME=Join-Path $StageRoot 'avd'
$env:TEMP=Join-Path $StageRoot 'tmp'
$env:TMP=$env:TEMP
$env:JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$($env:TEMP) -Djdk.net.unixdomain.tmpdir=$($env:TEMP) -Duser.home=$StageRoot/java-user"
$env:PYTHONDONTWRITEBYTECODE='1'
$env:HUNAN_EXTERNAL_SIGNING='1'
foreach($p in @($env:GRADLE_USER_HOME,$env:ANDROID_USER_HOME,$env:ANDROID_AVD_HOME,$env:USERPROFILE,$env:LOCALAPPDATA,$env:APPDATA,$env:TEMP)){New-Item -ItemType Directory -Force -Path $p|Out-Null}
