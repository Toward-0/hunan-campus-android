param(
    [ValidateSet('phone','arm32','x86_64')][string]$BuildAbi='phone',
    [switch]$SkipLint,
    [switch]$IsolationOnly
)
$ErrorActionPreference='Stop'
$ToolsConfig=Join-Path $PSScriptRoot 'tools.local.json'
$Tools=Get-Content -LiteralPath $ToolsConfig -Raw | ConvertFrom-Json
if (![Environment]::GetEnvironmentVariable($Tools.SigningPasswordVariable,'Process')) {
    throw 'Set the existing test keystore password in the configured process environment variable before building. Do not put it in logs or command arguments.'
}
$BuildParameters=@{
    OutputRoot=[string]$Tools.OutputRoot
    BuildAbi=$BuildAbi
    ToolsConfig=$ToolsConfig
    SkipLint=$SkipLint
    IsolationOnly=$IsolationOnly
}
& (Join-Path $PSScriptRoot 'source/build-stage.ps1') @BuildParameters
