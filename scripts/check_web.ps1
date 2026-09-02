$ErrorActionPreference = 'Stop'

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $workspaceRoot 'web'
$artifactRoot = Join-Path $workspaceRoot 'output\playwright'
$browserCode = Join-Path $PSScriptRoot 'check_web.playwright.js'
$npx = 'D:\Node\npx.cmd'
$session = 'baishi-one-check'
$url = 'http://127.0.0.1:5173/'
$startedServer = $null

function Invoke-CheckedCommand {
    param([scriptblock]$Command, [string]$FailureMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null

    Push-Location $webRoot
    try {
        Invoke-CheckedCommand { npm.cmd test -- --run } 'Frontend data tests failed.'
        Invoke-CheckedCommand { npm.cmd run build } 'Frontend production build failed.'
    }
    finally { Pop-Location }

    $serverReady = $false
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        $serverReady = $response.StatusCode -eq 200
    }
    catch { $serverReady = $false }

    if (-not $serverReady) {
        $startedServer = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1') -WorkingDirectory $webRoot -PassThru -WindowStyle Hidden
        foreach ($attempt in 1..30) {
            Start-Sleep -Milliseconds 500
            try {
                $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) { $serverReady = $true; break }
            }
            catch { }
        }
        if (-not $serverReady) { throw 'The local web server did not start within 15 seconds.' }
    }

    Push-Location $workspaceRoot
    try {
        & $npx --yes --package '@playwright/cli' playwright-cli "-s=$session" close 2>$null | Out-Null
        $browserStarted = $false
        foreach ($attempt in 1..3) {
            & $npx --yes --package '@playwright/cli' playwright-cli "-s=$session" open $url | Out-Null
            if ($LASTEXITCODE -eq 0) { $browserStarted = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $browserStarted) { throw 'Playwright browser startup failed after 3 attempts.' }

        & $npx --yes --package '@playwright/cli' playwright-cli "-s=$session" run-code "--filename=$browserCode"
        if ($LASTEXITCODE -ne 0) { throw 'Playwright page checks failed.' }
    }
    finally {
        & $npx --yes --package '@playwright/cli' playwright-cli "-s=$session" close 2>$null | Out-Null
        Pop-Location
    }

    Write-Host "`nUnified web checks passed. Screenshots: $artifactRoot" -ForegroundColor Green
}
finally {
    if ($null -ne $startedServer -and -not $startedServer.HasExited) {
        & taskkill.exe /PID $startedServer.Id /T /F 2>$null | Out-Null
    }
}
