$ErrorActionPreference='Stop'
. "$PSScriptRoot/../stage-env.ps1"
$project=Split-Path $PSScriptRoot -Parent
$tools='D:/codex/2026-10-30/ke-y/work/toolchain'
$cache="$tools/gradle-user/caches/modules-2/files-2.1"
$deps=@('org.jetbrains.kotlin/kotlin-compiler-embeddable/2.1.20','org.jetbrains.kotlin/kotlin-stdlib/2.1.20','org.jetbrains.kotlin/kotlin-script-runtime/2.1.20','org.jetbrains.kotlin/kotlin-reflect','org.jetbrains.intellij.deps/trove4j','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains/annotations/13.0')
$jars=@($deps | ForEach-Object {Get-ChildItem "$cache/$_" -Recurse -Filter *.jar | Select-Object -First 1 -ExpandProperty FullName})
$stdlib=Get-ChildItem "$cache/org.jetbrains.kotlin/kotlin-stdlib/2.1.20" -Recurse -Filter *.jar | Select-Object -First 1 -ExpandProperty FullName
$out="$project/build/repair-test"; New-Item -ItemType Directory -Force $out | Out-Null
& "$tools/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64/bin/java.exe" -cp ($jars -join ';') org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect -classpath $stdlib -d $out "$project/app/src/main/java/org/esurfing/hunan/SessionSnapshot.kt" "$project/app/src/main/java/org/esurfing/hunan/SessionRepairGate.kt" "$project/tests/SessionRepairRegression.kt"
if($LASTEXITCODE){throw 'Repair regression compilation failed'}
& "$tools/jdk/zulu17.60.17-ca-jdk17.0.16-win_x64/bin/java.exe" -cp "$out;$stdlib" org.esurfing.hunan.SessionRepairRegressionKt
if($LASTEXITCODE){throw 'Repair regression failed'}
