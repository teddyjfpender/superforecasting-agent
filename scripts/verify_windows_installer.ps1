# Hermetic release selection and integrity tests; no network or package install.
[CmdletBinding()]
param([string]$Case = "")
$ErrorActionPreference = "Stop"
if (-not $Case) {
    $engine = (Get-Process -Id $PID).Path
    $cases = @{
        "split" = "Release assets verified"; "backend-only" = "Release assets verified"
        "legacy" = "Release assets verified"
        "split-install" = "Installation sequence verified"
        "backend-only-install" = "Installation sequence verified"
        "corrupt" = "sha256 mismatch against SHA256SUMS"
        "missing" = "Missing or duplicate wheel asset"
        "duplicate" = "Missing or duplicate wheel asset"
        "manifest-mismatch" = "sha256 mismatch against release-manifest.json"
        "duplicate-checksum" = "Missing or duplicate checksum"
    }
    foreach ($name in $cases.Keys) {
        $output = & $engine -NoProfile -File $PSCommandPath -Case $name 2>&1
        $expectedExit = if ($cases[$name] -in @("Release assets verified", "Installation sequence verified")) { 0 } else { 1 }
        if ($LASTEXITCODE -ne $expectedExit -or ($output -join "`n") -notmatch [regex]::Escape($cases[$name])) {
            throw "Case $name exited $LASTEXITCODE, expected $expectedExit and '$($cases[$name])': $output"
        }
        Write-Host "PASS $name"
    }
    exit 0
}

$fixture = Join-Path ([IO.Path]::GetTempPath()) ("forecast-installer-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $fixture | Out-Null
$backend = "superforecasting_agent-9.9.9-py3-none-any.whl"
$terminal = "superforecasting_agent_tui-0.1.0-py3-none-any.whl"
foreach ($name in @($backend, $terminal)) {
    [IO.File]::WriteAllBytes((Join-Path $fixture $name), [Text.Encoding]::UTF8.GetBytes($name))
}
$backendSha = (Get-FileHash (Join-Path $fixture $backend) -Algorithm SHA256).Hash.ToLowerInvariant()
$terminalSha = (Get-FileHash (Join-Path $fixture $terminal) -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = @{
    version = "9.9.9"; tag = "v9.9.9"
    artifacts = @{
        wheel = @{name = $backend; sha256 = $backendSha}
        terminal_wheel = @{name = $terminal; sha256 = $terminalSha}
    }
}
$names = @($terminal, $backend, "SHA256SUMS", "release-manifest.json")
if ($Case -eq "legacy") {
    $manifest.artifacts.Remove("terminal_wheel")
    $names = @($backend, "SHA256SUMS", "release-manifest.json")
}
if ($Case -eq "missing") { $names = @($backend, "SHA256SUMS", "release-manifest.json") }
if ($Case -eq "duplicate") { $names += $terminal }
if ($Case -eq "manifest-mismatch") { $manifest.artifacts.terminal_wheel.sha256 = "0" * 64 }
$sums = "$backendSha  $backend`n$terminalSha  $terminal`n"
if ($Case -eq "duplicate-checksum") { $sums += "$backendSha  $backend`n" }
Set-Content -LiteralPath (Join-Path $fixture "SHA256SUMS") -Value $sums -Encoding Ascii
$manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $fixture "release-manifest.json")
if ($Case -eq "corrupt") { Set-Content (Join-Path $fixture $terminal) "corrupt" }
if ($Case -like "backend-only*") { Remove-Item (Join-Path $fixture $terminal) }
$release = @{
    tag_name = "v9.9.9"
    assets = @($names | ForEach-Object { @{name = $_; browser_download_url = "https://fixture.invalid/$_"} })
}
function Invoke-RestMethod {
    param([switch]$UseBasicParsing, [string]$Uri)
    return $release
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile)
    $name = ([uri]$Uri).Segments[-1]
    Copy-Item -LiteralPath (Join-Path $fixture $name) -Destination $OutFile
}
# User pins must not leak into the fixture's release selection.
foreach ($name in @("MANIFEST", "TAG", "SUPERFORECASTING_AGENT_RELEASE_TAG", "ALLOW_UNVERIFIED", "SUPERFORECASTING_AGENT_ALLOW_UNVERIFIED")) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
$env:SUPERFORECASTING_AGENT_HOME = Join-Path $fixture "profile"
$env:FORECAST_INSTALL_TEST_LOG = Join-Path $fixture "python-calls.log"
$fakePython = Join-Path $fixture "python.ps1"
@'
Add-Content -LiteralPath $env:FORECAST_INSTALL_TEST_LOG -Value ($args -join " ")
$global:LASTEXITCODE = 0
'@ | Set-Content -LiteralPath $fakePython
function Get-Command {
    param([string]$Name, [string]$ErrorAction)
    return [pscustomobject]@{Source = $fakePython}
}
try {
    $install = $Case -like "*-install"
    & (Join-Path $PSScriptRoot "install-release.ps1") -Tag v9.9.9 -VerifyOnly:(-not $install) -BackendOnly:($Case -like "backend-only*")
    if ($install) {
        $calls = Get-Content -Raw -LiteralPath $env:FORECAST_INSTALL_TEST_LOG
        if ($calls -notmatch "pipx install --force .*superforecasting_agent-9.9.9") {
            throw "Backend was not installed: $calls"
        }
        if ($Case -eq "split-install") {
            if ($calls -notmatch "pipx inject --force superforecasting-agent .*superforecasting_agent_tui-0.1.0" -or
                $calls.IndexOf("pipx inject") -lt $calls.IndexOf("pipx install")) {
                throw "Companion was not installed after backend: $calls"
            }
        } elseif ($calls -match "pipx inject") { throw "Backend-only installed a companion." }
        Write-Host "Installation sequence verified"
    }
} finally {
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
