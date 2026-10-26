[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8501,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = $null
        $probe = 'import sys; print(sys.executable)'
        foreach ($candidate in @(
            @{ Name = 'py'; Arguments = @('-3', '-c', $probe) },
            @{ Name = 'python'; Arguments = @('-c', $probe) },
            @{ Name = 'uv'; Arguments = @('python', 'find') }
        )) {
            $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
            if ($null -eq $command) { continue }
            try {
                $candidateArgs = $candidate.Arguments
                $result = @(& $command.Source @candidateArgs 2>$null)
                if ($LASTEXITCODE -eq 0 -and $result.Count -gt 0) {
                    $path = ([string]$result[-1]).Trim()
                    if (Test-Path -LiteralPath $path -PathType Leaf) { $python = $path; break }
                }
            } catch { continue }
        }
    }
    if (-not $python) { throw 'Python was not found. Run setup.ps1 first.' }
    $ready = $false
    try {
        & $python -c "import sys; assert sys.version_info >= (3, 10); import streamlit" *> $null
        $ready = $LASTEXITCODE -eq 0
    } catch { $ready = $false }
    if (-not $ready) { throw 'Python 3.10+ and Streamlit are required. Run setup.ps1 first.' }
    $headless = if ($NoBrowser) { 'true' } else { 'false' }
    Write-Host "Opening the local vocabulary app at http://127.0.0.1:$Port (Ctrl+C to stop)."
    & $python -m streamlit run (Join-Path $PSScriptRoot 'app.py') `
        --server.address 127.0.0.1 --server.port $Port `
        --browser.serverAddress 127.0.0.1 --server.headless $headless `
        --browser.gatherUsageStats false
    if ($LASTEXITCODE -ne 0) { throw 'The app stopped with an error. Check the message above or choose another -Port.' }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
