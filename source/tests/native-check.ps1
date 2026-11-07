param()
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/../stage-env.ps1"
# Run from the project directory. Set GCC_BIN and JAVA_HOME to installed toolchains.
$root = Split-Path $PSScriptRoot -Parent
$testDir = Join-Path $root 'build/native-test'
New-Item -ItemType Directory -Force $testDir | Out-Null
$env:Path = "$env:GCC_BIN;$env:Path"
$base = Join-Path $root 'vendor/hunan'
& gcc -shared -O2 -Wall -Wextra -I "$base/include" -I "$base/src" -I "$env:JAVA_HOME/include" -I "$env:JAVA_HOME/include/win32" `
    "$root/app/src/main/cpp/bridge.c" "$base/src/hunan/HunanXml.c" `
    "$base/src/cipher/algo/hunan/aes_double_cbc_hunan.c" "$base/src/cipher/KeyData.c" `
    "$root/app/src/main/cpp/memory_hex.c" "$base/src/utils/sim/SimEvpAes.c" -o "$testDir/hunan_core.dll"
if ($LASTEXITCODE -ne 0) { throw 'Native compilation failed' }
& "$env:JAVA_HOME/bin/javac.exe" -d $testDir "$PSScriptRoot/NativeStress.java"
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed' }
& "$env:JAVA_HOME/bin/java.exe" "-Dhunan.library=$testDir/hunan_core.dll" -cp $testDir org.esurfing.hunan.NativeStress
if ($LASTEXITCODE -ne 0) { throw 'Native checks failed' }
