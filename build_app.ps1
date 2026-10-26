[CmdletBinding()]
param([switch]$IncludePersonalData)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$previousPersonalFlag = $env:DEUTSCH_VOCAB_INCLUDE_PERSONAL_DATA
$env:DEUTSCH_VOCAB_INCLUDE_PERSONAL_DATA = if ($IncludePersonalData) { '1' } else { '0' }
Push-Location -LiteralPath $root
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    & $python -m PyInstaller --noconfirm (Join-Path $root 'DeutschWortschatz.spec')
    if ($LASTEXITCODE -ne 0) { throw '打包失败；请查看 PyInstaller 输出。' }
    & $python (Join-Path $root 'tools\package_release.py')
    if ($LASTEXITCODE -ne 0) { throw '压缩包生成失败。' }
    Write-Host "应用已生成：$(Join-Path $root 'dist\DeutschWortschatz\DeutschWortschatz.exe')"
} finally {
    $env:DEUTSCH_VOCAB_INCLUDE_PERSONAL_DATA = $previousPersonalFlag
    Pop-Location
}
