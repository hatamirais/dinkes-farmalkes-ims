param(
    [string]$Target = "apps.items",
    [switch]$NoActivate
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if (-not $NoActivate) {
        $activatePath = Join-Path $repoRoot "venv\Scripts\Activate.ps1"
        if (Test-Path $activatePath) {
            . $activatePath
        }
        else {
            Write-Warning "Virtualenv activation script not found at $activatePath"
            Write-Warning "Continuing with current Python environment."
        }
    }

    Set-Location (Join-Path $repoRoot "backend")

    python -c "import crispy_forms" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Missing dependency: crispy_forms" -ForegroundColor Yellow
        Write-Host "Run: pip install -r requirements.txt" -ForegroundColor Yellow
        exit 1
    }

    python manage.py test $Target
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
