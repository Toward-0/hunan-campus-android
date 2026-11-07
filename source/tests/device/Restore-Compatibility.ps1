#requires -Version 7.0
param([Parameter(Mandatory)][string]$Adb,[Parameter(Mandatory)][string]$Aapt,[Parameter(Mandatory)][string]$Serial,[Parameter(Mandatory)][ValidateSet('org.esurfing.hunan.isolation')][string]$Package,[Parameter(Mandatory)][string]$Apk,[Parameter(Mandatory)][string]$EvidenceDirectory)
$ErrorActionPreference='Stop'
# Does not uninstall or clear either package. Only stop the isolated fixture.
& "$PSScriptRoot/Verify-Compatibility.ps1" -Adb $Adb -Aapt $Aapt -Serial $Serial -Package $Package -Apk $Apk -EvidenceDirectory $EvidenceDirectory -Action Stop -TimeoutSeconds 30
if($LASTEXITCODE){throw 'Isolation cleanup failed'}
Write-Output 'Isolation stopped. Main application and its settings are untouched. Restore any manually changed font/navigation settings using your recorded pre-test values.'
