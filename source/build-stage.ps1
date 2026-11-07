param([Parameter(Mandatory)][string]$OutputRoot,[ValidateSet('phone','arm32','x86_64')][string]$BuildAbi='phone',[switch]$SkipLint,[switch]$IsolationOnly)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/stage-env.ps1"
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if(Test-Path (Join-Path $OutputRoot 'SEALED')){throw 'Output is sealed'}
foreach($protected in @('D:/codex/2026-11-05/jian/work','D:/codex/2026-11-05/jian/outputs')) {
 $protected=[IO.Path]::GetFullPath($protected).TrimEnd('\')
 if($OutputRoot -eq $protected -or $OutputRoot.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Historical output root is protected'}
}
New-Item -ItemType Directory -Force -Path $OutputRoot,"$StageRoot/evidence","$StageRoot/pack"|Out-Null
$runStamp=Get-Date -Format 'yyyyMMdd-HHmmss'
foreach($name in @("build-$BuildAbi.log","build-command-$BuildAbi.json","build-exit-$BuildAbi.json")){
 $previous=Join-Path "$StageRoot/evidence" $name
 if(Test-Path -LiteralPath $previous){Copy-Item -LiteralPath $previous -Destination "$StageRoot/evidence/$runStamp-previous-$name"}
}
('sdk.dir='+$env:ANDROID_HOME.Replace('\','/'))|Set-Content "$PSScriptRoot/local.properties" -Encoding ascii
$tasks=@(':app:assembleIsolation')
if(!$IsolationOnly){if($BuildAbi -ne 'phone'){throw 'Main APK is phone ABI only'}; $tasks+=':app:assembleCandidate'}
if(!$SkipLint){$tasks+=':app:lintCandidate';$tasks+=':app:lintIsolation'}
$gradle='D:/codex/2026-10-30/ke-y/work/toolchain/gradle/gradle-8.11.1/bin/gradle.bat'
$argsList=@('-p',$PSScriptRoot,'--offline','--no-daemon',"-PtestAbi=$BuildAbi")+$tasks
@{command=$gradle;arguments=$argsList;environment=@{gradle=$env:GRADLE_USER_HOME;sdk=$env:ANDROID_HOME;android=$env:ANDROID_USER_HOME;avd=$env:ANDROID_AVD_HOME;temp=$env:TEMP;javaOptions=$env:JAVA_TOOL_OPTIONS};time=(Get-Date).ToString('o')}|ConvertTo-Json -Depth 5|Set-Content "$StageRoot/evidence/build-command-$BuildAbi.json"
& $gradle @argsList 2>&1|Tee-Object "$StageRoot/evidence/build-$BuildAbi.log"
$buildExit=$LASTEXITCODE
@{exitCode=$buildExit;time=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content "$StageRoot/evidence/build-exit-$BuildAbi.json"
if($buildExit -ne 0){throw "Build failed: $buildExit"}
$key='D:/codex/2026-10-30/ke-y/work/toolchain/android-user/debug.keystore'
if(!(Test-Path -LiteralPath $key)){throw 'Existing test key missing'}
$variants=@('isolation');if(!$IsolationOnly){$variants+='candidate'}
foreach($variant in $variants){
 $inputApk="$PSScriptRoot/app/build/outputs/apk/$variant/app-$variant-unsigned.apk"
 $aligned="$StageRoot/pack/$variant-$BuildAbi-aligned.apk"
 $apk=Join-Path $OutputRoot "ESurfingHunan-0.2.21-compat-s1-$variant-$BuildAbi.apk"
 & "$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe" -f -P 16 4 $inputApk $aligned
 if($LASTEXITCODE){throw 'zipalign failed'}
 & "$env:JAVA_HOME/bin/java.exe" -jar "$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" sign --ks $key --ks-pass pass:android --out $apk $aligned
 if($LASTEXITCODE){throw 'Signing failed'}
 & "$env:JAVA_HOME/bin/java.exe" -jar "$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs $apk 2>&1|Tee-Object "$StageRoot/evidence/signature-$variant-$BuildAbi.txt"
 if($LASTEXITCODE){throw 'Signature verification failed'}
 & "$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe" -c -P 16 -v 4 $apk 2>&1|Tee-Object "$StageRoot/evidence/zipalign-$variant-$BuildAbi.txt"
 if($LASTEXITCODE){throw 'Final APK alignment failed'}
 Get-FileHash -LiteralPath $apk -Algorithm SHA256|Select-Object Path,Hash
}
