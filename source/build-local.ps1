param([Parameter(Mandatory)][string]$OutputRoot,[ValidateSet('phone','arm32','x86_64')][string]$BuildAbi='phone',[switch]$SkipLint,[switch]$IsolationOnly)
& "$PSScriptRoot/build-stage.ps1" @PSBoundParameters
