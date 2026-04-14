# Maximalist validation gate for IRIS (Windows / PowerShell).
# Mirrors scripts/check.sh. Runs the Standard validation gate from docs/REVAMP.md.

$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$fail = 0
function Invoke-Gate {
    param([string]$Label, [scriptblock]$Block)
    Write-Host ""
    Write-Host "==> $Label"
    & $Block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: $Label" -ForegroundColor Red
        $script:fail = 1
    }
}

Write-Host "=== Python gate ==="
Invoke-Gate "uv run ruff format --check src tests" { uv run ruff format --check src tests }
Invoke-Gate "uv run ruff check src tests"          { uv run ruff check src tests }
Invoke-Gate "uv run pyright src/iris"              { uv run pyright src/iris }
Invoke-Gate "uv run pytest -x -q"                  { uv run pytest -x -q }
Invoke-Gate "uvx semgrep --config=auto --error src/iris" { uvx semgrep --config=auto --error src/iris }
Invoke-Gate "uv run vulture src/iris --min-confidence 80" { uv run vulture src/iris --min-confidence 80 }

if (Test-Path "iris-app") {
    Write-Host ""
    Write-Host "=== TypeScript gate (iris-app/) ==="
    Push-Location iris-app
    try {
        Invoke-Gate "npx tsc --noEmit" { npx tsc --noEmit }
        $pkg = Get-Content package.json -Raw
        if ($pkg -match '"lint"\s*:') {
            Invoke-Gate "npm run lint" { npm run lint }
        } else {
            Write-Host "(iris-app: no lint script yet — skipping)"
        }
    } finally {
        Pop-Location
    }
}

if ($fail -ne 0) {
    Write-Host ""
    Write-Host "check.ps1: one or more gates FAILED" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "check.ps1: all gates passed" -ForegroundColor Green
