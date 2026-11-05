param(
    [string[]]$Target = @("apps.items"),
    [switch]$NoActivate,
    [switch]$KeepDb
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

function Normalize-TestLabel {
    param(
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Label)) {
        return $null
    }

    if ($Label -match '^apps\.[^.]+$') {
        return "$Label.tests"
    }

    return $Label
}

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

    python -c "import django" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Missing dependency: django" -ForegroundColor Yellow
        Write-Host "Run: pip install -r requirements.txt" -ForegroundColor Yellow
        exit 1
    }

    $normalizedTargets = @($Target | ForEach-Object { Normalize-TestLabel $_ } | Where-Object { $_ })
    if ($normalizedTargets.Count -eq 0) {
        Write-Error "No valid test targets were provided."
    }

    foreach ($testTarget in $normalizedTargets) {
        Write-Host "Running tests for $testTarget" -ForegroundColor Cyan
        $args = @("manage.py", "test", "--noinput")
        if ($KeepDb) {
            $args += "--keepdb"
        }
        $args += $testTarget

        python @args
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    exit 0
}
finally {
    Pop-Location
}
