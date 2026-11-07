$ErrorActionPreference='Stop'
. "$PSScriptRoot/../stage-env.ps1"
$project=Split-Path $PSScriptRoot -Parent
$tools='D:/codex/2026-10-30/ke-y/work/toolchain'
$cache="$tools/gradle-user/caches/modules-2/files-2.1"
$deps=@('org.jetbrains.kotlin/kotlin-compiler-embeddable/2.1.20','org.jetbrains.kotlin/kotlin-stdlib/2.1.20','org.jetbrains.kotlin/kotlin-script-runtime/2.1.20','org.jetbrains.kotlin/kotlin-reflect','org.jetbrains.intellij.deps/trove4j','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains/annotations/13.0')
$jars=@($deps | ForEach-Object {Get-ChildItem "$cache/$_" -Recurse -Filter *.jar | Select-Object -First 1 -ExpandProperty FullName})
$stdlib=Get-ChildItem "$cache/org.jetbrains.kotlin/kotlin-stdlib/2.1.20" -Recurse -Filter *.jar | Select-Object -First 1 -ExpandProperty FullName
$out="$project/build/internet-test"; New-Item -ItemType Directory -Force $out | Out-Null
$tempDir=$env:TEMP; New-Item -ItemType Directory -Force $tempDir | Out-Null
# JAVA_TOOL_OPTIONS inherited from stage-env.ps1
$files=@('SessionSnapshot','HttpScope','OwnedHttpTransport','InternetCheck') | ForEach-Object {"$project/app/src/main/java/org/esurfing/hunan/$_.kt"}
$files+=Get-ChildItem "$PSScriptRoot/jvm-stubs/*.kt" | Select-Object -ExpandProperty FullName
$files+="$PSScriptRoot/InternetRegression.kt"
$files+="$PSScriptRoot/TransportRegression.kt"
$runtime=(@($stdlib)+@(Get-ChildItem "$project/app/libs/*.jar" | Select-Object -ExpandProperty FullName)) -join ';'
& "$tools/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64/bin/java.exe" -cp ($jars -join ';') org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect -classpath $runtime -d $out @files
if($LASTEXITCODE){throw 'Internet regression compilation failed'}
& "$tools/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64/bin/java.exe" -cp "$out;$runtime" org.esurfing.hunan.InternetRegressionKt
if($LASTEXITCODE){throw 'Internet regression failed'}
& "$tools/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64/bin/java.exe" -cp "$out;$runtime" org.esurfing.hunan.TransportRegressionKt
if($LASTEXITCODE){throw 'Transport regression failed'}
