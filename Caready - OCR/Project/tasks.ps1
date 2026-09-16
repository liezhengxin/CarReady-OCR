<#
.SYNOPSIS
    Task runner for the Caready monorepo (Windows / PowerShell).

.DESCRIPTION
    A Makefile equivalent for the primary development environment, which is
    Windows. `make` is not assumed to be installed.

.EXAMPLE
    .\tasks.ps1 up
    .\tasks.ps1 test
    .\tasks.ps1 seed -Reset
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'up', 'down', 'reset', 'logs', 'seed', 'migrate', 'revision',
                 'check', 'test', 'test-api', 'test-seed', 'test-web', 'lint', 'format',
                 'gen-key', 'doctor')]
    [string]$Task = 'help',

    [switch]$Reset,
    [switch]$NoImages,
    [string]$Message = 'change'
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$ApiDir = Join-Path $Root 'services\api'
$WebDir = Join-Path $Root 'apps\web'

function Write-Step([string]$text) {
    Write-Host "`n>> $text" -ForegroundColor Cyan
}

function Invoke-Checked([scriptblock]$block, [string]$what) {
    & $block
    if ($LASTEXITCODE -ne 0) {
        throw "$what failed with exit code $LASTEXITCODE"
    }
}

switch ($Task) {

    'help' {
        Write-Host @'
Caready task runner

  up          Build and start the full stack (seeds automatically)
  down        Stop the stack, keep volumes
  reset       Stop the stack and DELETE all volumes (destroys the database)
  logs        Tail logs from every service
  seed        Seed synthetic data      [-Reset] [-NoImages]
  migrate     Apply migrations
  revision    Autogenerate a migration [-Message "what changed"]
  check       Verify the schema matches the ORM metadata
  test        Run every test suite
  test-api    API tests only
  test-seed   Generator determinism and calibration only
  test-web    Web tests only
  lint        Ruff check + web lint
  format      Ruff format
  gen-key     Generate a PII encryption key
  doctor      Report which tools are installed

Examples:
  .\tasks.ps1 up
  .\tasks.ps1 seed -Reset -NoImages
  .\tasks.ps1 revision -Message "add damage detection index"
'@ -ForegroundColor Gray
    }

    'doctor' {
        Write-Step 'Toolchain'
        $tools = @(
            @{ Name = 'docker';  Args = '--version'; Required = $true  },
            @{ Name = 'python';  Args = '--version'; Required = $true  },
            @{ Name = 'node';    Args = '--version'; Required = $true  },
            @{ Name = 'npm';     Args = '--version'; Required = $true  },
            @{ Name = 'git';     Args = '--version'; Required = $true  }
        )
        $missing = @()
        foreach ($tool in $tools) {
            $found = Get-Command $tool.Name -ErrorAction SilentlyContinue
            if ($found) {
                $version = (& $tool.Name $tool.Args 2>$null | Select-Object -First 1)
                Write-Host ("  {0,-8} {1}" -f $tool.Name, $version) -ForegroundColor Green
            }
            else {
                Write-Host ("  {0,-8} NOT INSTALLED" -f $tool.Name) -ForegroundColor Red
                if ($tool.Required) { $missing += $tool.Name }
            }
        }
        if ($missing.Count -gt 0) {
            Write-Host "`nMissing: $($missing -join ', ')" -ForegroundColor Yellow
            Write-Host 'Install Docker Desktop (WSL2 backend), Python 3.11, Node 22, and Git.' -ForegroundColor Yellow
            Write-Host 'See docs/OPEN_ITEMS.md #9.' -ForegroundColor Yellow
            exit 1
        }
        Write-Host "`nAll required tools present." -ForegroundColor Green
    }

    'up' {
        if (-not (Test-Path (Join-Path $Root '.env'))) {
            Write-Step 'Creating .env from .env.example'
            Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
        }
        Write-Step 'Starting the stack'
        Invoke-Checked { docker compose up --build -d } 'docker compose up'
        Write-Host @'

  Web         http://localhost:3000
  API docs    http://localhost:8000/docs
  MinIO       http://localhost:9001
  MLflow      http://localhost:5500

  Demo login: inspektur@caready.local / caready-dev-2026

  ALL DATA IS SYNTHETIC AND HAS NO REAL-WORLD VALIDITY.
'@ -ForegroundColor Green
    }

    'down'  { Write-Step 'Stopping'; docker compose down }

    'reset' {
        Write-Host 'This DELETES the database, object storage, and MLflow volumes.' -ForegroundColor Yellow
        $answer = Read-Host 'Type "yes" to continue'
        if ($answer -ne 'yes') { Write-Host 'Cancelled.'; break }
        docker compose down -v
    }

    'logs'  { docker compose logs -f }

    'seed' {
        $seedArgs = @()
        if ($Reset)    { $seedArgs += '--reset' }
        if ($NoImages) { $seedArgs += '--no-images' }
        Write-Step "Seeding synthetic data $($seedArgs -join ' ')"
        Invoke-Checked { docker compose run --rm seed python /app/seed/run_seed.py @seedArgs } 'seed'
    }

    'migrate' {
        Write-Step 'Applying migrations'
        Push-Location $ApiDir
        try { Invoke-Checked { alembic upgrade head } 'alembic upgrade' }
        finally { Pop-Location }
    }

    'revision' {
        Write-Step "Generating migration: $Message"
        Push-Location $ApiDir
        try { Invoke-Checked { alembic revision --autogenerate -m $Message } 'alembic revision' }
        finally { Pop-Location }
    }

    'check' {
        Write-Step 'Checking schema against ORM metadata'
        Push-Location $ApiDir
        try { Invoke-Checked { alembic check } 'alembic check' }
        finally { Pop-Location }
    }

    'test-api' {
        Write-Step 'API tests'
        Push-Location $ApiDir
        try { Invoke-Checked { pytest } 'pytest' }
        finally { Pop-Location }
    }

    'test-seed' {
        Write-Step 'Generator determinism and calibration'
        Push-Location $Root
        try { Invoke-Checked { pytest seed/tests -v } 'pytest' }
        finally { Pop-Location }
    }

    'test-web' {
        Write-Step 'Web tests'
        Push-Location $WebDir
        try { Invoke-Checked { npm test } 'npm test' }
        finally { Pop-Location }
    }

    'test' {
        & $PSCommandPath test-api
        & $PSCommandPath test-seed
        & $PSCommandPath test-web
    }

    'lint' {
        Write-Step 'Ruff'
        Push-Location $Root
        try { Invoke-Checked { ruff check services packages seed } 'ruff check' }
        finally { Pop-Location }

        Write-Step 'Web lint'
        Push-Location $WebDir
        try { Invoke-Checked { npm run lint } 'npm run lint' }
        finally { Pop-Location }
    }

    'format' {
        Write-Step 'Ruff format'
        Push-Location $Root
        try { ruff format services packages seed }
        finally { Pop-Location }
    }

    'gen-key' {
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        Write-Host 'Prepend this to PII_ENCRYPTION_KEYS. Keep the old key until re-encryption completes.' -ForegroundColor Yellow
    }
}
