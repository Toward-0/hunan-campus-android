param([Parameter(Mandatory)][string]$OutputRoot,[ValidateSet('phone','arm32','x86_64')][string]$BuildAbi='phone',[switch]$SkipLint,[switch]$IsolationOnly,[string]$ToolsConfig)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/stage-env.ps1" -ToolsConfig $ToolsConfig
$OutputRoot=Assert-StageWritePath $OutputRoot
if($OutputRoot.TrimEnd('\','/') -ne $StageOutputRoot){throw 'OutputRoot must match current-stage configuration'}
if(!$IsolationOnly -and $BuildAbi -ne 'phone'){throw 'Main APK is phone ABI only'}
$passwordVariable=[string]$StageTools.SigningPasswordVariable
if($passwordVariable -notmatch '^[A-Za-z_][A-Za-z0-9_]*$'){throw 'Invalid signing environment variable name'}
if(![Environment]::GetEnvironmentVariable($passwordVariable,'Process')){throw 'Signing password environment variable missing; do not store its value in reports'}
$gradleFile=Get-Content -LiteralPath "$PSScriptRoot/app/build.gradle.kts" -Raw -Encoding UTF8
$nameMatch=[regex]::Match($gradleFile,'versionName\s*=\s*"([A-Za-z0-9._-]+)"')
$codeMatch=[regex]::Match($gradleFile,'versionCode\s*=\s*(\d+)')
if(!$nameMatch.Success -or !$codeMatch.Success){throw 'Cannot read version from actual build input'}
$versionName=$nameMatch.Groups[1].Value
$versionCode=[int]$codeMatch.Groups[1].Value
if($versionCode -le 33){throw 'New code delivery versionCode must exceed 33'}
$runStamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot=Assert-StageWritePath (Join-Path $StageRoot "evidence/build-$BuildAbi-$runStamp")
New-Item -ItemType Directory -Path $runRoot|Out-Null
$localProperties=Assert-StageWritePath (Join-Path $PSScriptRoot 'local.properties')
('sdk.dir='+$env:ANDROID_HOME.Replace('\','/'))|Set-Content -LiteralPath $localProperties -Encoding ascii
$tasks=@(':app:assembleIsolation')
if(!$IsolationOnly){$tasks+=':app:assembleCandidate'}
if(!$SkipLint){if(!$IsolationOnly){$tasks+=':app:lintCandidate'};$tasks+=':app:lintIsolation'}
$gradle=$StageTools.GradleExecutable
$argsList=@('-p',$PSScriptRoot,'--offline','--no-daemon','--project-cache-dir',(Join-Path $StageRoot 'gradle-project'),"-PtestAbi=$BuildAbi")+$tasks
@{command=$gradle;arguments=$argsList;versionName=$versionName;versionCode=$versionCode;environment=@{gradle=$env:GRADLE_USER_HOME;sdk=$env:ANDROID_HOME;android=$env:ANDROID_USER_HOME;avd=$env:ANDROID_AVD_HOME;temp=$env:TEMP;javaOptions=$env:JAVA_TOOL_OPTIONS};time=(Get-Date).ToString('o')}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath "$runRoot/build-command.json" -Encoding UTF8
& $gradle @argsList 2>&1|Tee-Object -FilePath "$runRoot/build.log"
$buildExit=$LASTEXITCODE
@{exitCode=$buildExit;time=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath "$runRoot/build-exit.json" -Encoding UTF8
if($buildExit -ne 0){throw "Build failed: $buildExit"}
$variants=@('isolation');if(!$IsolationOnly){$variants+='candidate'}
foreach($variant in $variants){
 $inputApk=Assert-StageWritePath "$PSScriptRoot/app/build/outputs/apk/$variant/app-$variant-unsigned.apk"
 if(!(Test-Path -LiteralPath $inputApk -PathType Leaf)){throw "Unsigned APK missing: $variant"}
 $aligned=Assert-StageWritePath "$StageRoot/pack/$variant-$BuildAbi-$runStamp-aligned.apk"
 $apk=Assert-StageWritePath (Join-Path $OutputRoot "ESurfingHunan-$versionName-$variant-$BuildAbi.apk")
 if(Test-Path -LiteralPath $apk){throw 'APK output exists; preserve the current-stage iteration explicitly before rebuilding'}
 @(
  @{command="$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe";arguments=@('-f','-P','16','4',$inputApk,$aligned)},
  @{command="$env:JAVA_HOME/bin/java.exe";arguments=@('-jar',"$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar",'sign','--ks',$StageTools.TestKeystore,'--ks-pass',"env:$passwordVariable",'--out',$apk,$aligned)},
  @{command="$env:JAVA_HOME/bin/java.exe";arguments=@('-jar',"$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar",'verify','--verbose','--print-certs',$apk)},
  @{command="$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe";arguments=@('-c','-P','16','-v','4',$apk)}
 )|ConvertTo-Json -Depth 6|Set-Content -LiteralPath "$runRoot/packaging-commands-$variant.json" -Encoding UTF8
 $steps=@()
 & "$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe" -f -P 16 4 $inputApk $aligned
 $code=$LASTEXITCODE;$steps+=@{step='zipalign';exitCode=$code}
 $steps|ConvertTo-Json -Depth 4|Set-Content -LiteralPath "$runRoot/packaging-exits-$variant.json" -Encoding UTF8
 if($code -ne 0){throw "zipalign failed: $code"}
 & "$env:JAVA_HOME/bin/java.exe" -jar "$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" sign --ks $StageTools.TestKeystore --ks-pass "env:$passwordVariable" --out $apk $aligned
 $code=$LASTEXITCODE;$steps+=@{step='sign';exitCode=$code}
 $steps|ConvertTo-Json -Depth 4|Set-Content -LiteralPath "$runRoot/packaging-exits-$variant.json" -Encoding UTF8
 if($code -ne 0){throw "Signing failed: $code"}
 & "$env:JAVA_HOME/bin/java.exe" -jar "$env:ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs $apk 2>&1|Tee-Object -FilePath "$runRoot/signature-$variant.txt"
 $code=$LASTEXITCODE;$steps+=@{step='verify';exitCode=$code}
 $steps|ConvertTo-Json -Depth 4|Set-Content -LiteralPath "$runRoot/packaging-exits-$variant.json" -Encoding UTF8
 if($code -ne 0){throw "Signature verification failed: $code"}
 $signatureText=Get-Content -LiteralPath "$runRoot/signature-$variant.txt" -Raw -Encoding UTF8
 if($signatureText -notmatch 'certificate SHA-256 digest:\s*2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229'){throw 'APK certificate does not match the existing test certificate'}
 & "$env:ANDROID_HOME/build-tools/35.0.0/zipalign.exe" -c -P 16 -v 4 $apk 2>&1|Tee-Object -FilePath "$runRoot/zipalign-$variant.txt"
 $code=$LASTEXITCODE;$steps+=@{step='final-zipalign';exitCode=$code}
 $steps|ConvertTo-Json -Depth 4|Set-Content -LiteralPath "$runRoot/packaging-exits-$variant.json" -Encoding UTF8
 if($code -ne 0){throw "Final APK alignment failed: $code"}
 Get-FileHash -LiteralPath $apk -Algorithm SHA256|Select-Object Path,Hash
}
