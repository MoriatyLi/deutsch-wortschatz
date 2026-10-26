[CmdletBinding()]
param([switch]$Tts)

$ErrorActionPreference = 'Stop'

function Test-SupportedPython {
    param([string]$Executable)
    try {
        & $Executable -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Test-PipAvailable {
    param([string]$Executable)
    try {
        & $Executable -m pip --version *> $null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-BasePython {
    $probe = 'import sys; print(sys.executable)'
    $candidates = @(
        @{ Name = 'py'; Arguments = @('-3', '-c', $probe) },
        @{ Name = 'python'; Arguments = @('-c', $probe) },
        @{ Name = 'uv'; Arguments = @('python', 'find') }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if ($null -eq $command) { continue }
        try {
            $candidateArgs = $candidate.Arguments
            $result = @(& $command.Source @candidateArgs 2>$null)
            if ($LASTEXITCODE -ne 0 -or $result.Count -eq 0) { continue }
            $path = ([string]$result[-1]).Trim()
            if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Test-SupportedPython $path)) {
                return $path
            }
        } catch { continue }
    }
    throw 'Python 3.10+ was not found. Install Python with pip, reopen this terminal, and run setup.ps1 again.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $venvDirectory = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
    $basePython = $null
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $basePython = Find-BasePython
        $environmentCreated = $false
        try {
            & $basePython -m venv $venvDirectory
            $environmentCreated = $LASTEXITCODE -eq 0
        } catch { $environmentCreated = $false }
        if (-not $environmentCreated) {
            # Some distributions omit ensurepip. Create only the environment,
            # then use the available base pip with --python below.
            Write-Host 'Retrying environment creation without bundled pip...'
            & $basePython -m venv --without-pip $venvDirectory
            if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Install a Python distribution containing venv.' }
        }
    }
    if (-not (Test-SupportedPython $venvPython)) {
        throw 'The existing .venv requires Python 3.10+. Rename it and rerun setup.ps1; data is kept separately.'
    }
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    if ($Tts) { $requirements = Join-Path $PSScriptRoot 'requirements-tts.txt' }

    $hasVenvPip = Test-PipAvailable $venvPython
    if (-not $hasVenvPip) {
        $pipBootstrapped = $false
        try {
            & $venvPython -m ensurepip --upgrade 2>$null
            $pipBootstrapped = $LASTEXITCODE -eq 0
        } catch { $pipBootstrapped = $false }
        if ($pipBootstrapped) {
            $hasVenvPip = Test-PipAvailable $venvPython
        }
    }
    if ($hasVenvPip) {
        & $venvPython -m pip install -r $requirements
    } else {
        if ($null -eq $basePython) { $basePython = Find-BasePython }
        if (-not (Test-PipAvailable $basePython)) {
            throw 'Both ensurepip and base pip are unavailable. Install Python with pip, then rerun setup.ps1.'
        }
        Write-Host 'Installing into .venv through base pip --python (pip 22.3+ required)...'
        & $basePython -m pip --python $venvPython install -r $requirements
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network/proxy settings and retry setup.ps1.' }
    Write-Host 'Setup complete. Double-click start.bat or run .\start.ps1.'
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
