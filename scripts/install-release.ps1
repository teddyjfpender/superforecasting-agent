[CmdletBinding()]
param(
    [string]$Tag = "",
    [string]$Manifest = "",
    [switch]$AllowUnverified,
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$Repo = "teddyjfpender/superforecasting-agent"
$Binary = "superforecasting-agent"

function Fail([string]$Message) {
    throw $Message
}

function Download([string]$Uri, [string]$Destination) {
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
}

function Read-ReleaseManifest([string]$Path) {
    $data = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    $wheel = $data.artifacts.wheel
    if ([string]$data.version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$' -or
        [string]$data.tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$' -or
        [string]$wheel.name -notmatch '^[A-Za-z0-9_.+-]+\.whl$' -or
        ([string]$wheel.sha256) -notmatch '^[0-9a-fA-F]{64}$') {
        Fail "Release manifest is missing its version, tag, wheel name, or wheel sha256."
    }
    return [pscustomobject]@{
        Version = [string]$data.version
        Tag = [string]$data.tag
        WheelName = [string]$wheel.name
        WheelSha256 = ([string]$wheel.sha256).ToLowerInvariant()
    }
}

function Find-SupportedPython {
    $candidates = @(
        [pscustomobject]@{ Exe = "py"; Args = [string[]]@("-3.13") },
        [pscustomobject]@{ Exe = "py"; Args = [string[]]@("-3.12") },
        [pscustomobject]@{ Exe = "py"; Args = [string[]]@("-3.11") },
        [pscustomobject]@{ Exe = "python"; Args = [string[]]@() },
        [pscustomobject]@{ Exe = "python3"; Args = [string[]]@() }
    )
    foreach ($candidate in $candidates) {
        try {
            $exe = (Get-Command $candidate.Exe -ErrorAction Stop).Source
            $prefix = $candidate.Args
            & $exe @prefix -c "import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ Exe = $exe; Args = $prefix }
            }
        } catch {
            continue
        }
    }
    return $null
}

$explicitTag = $Tag.Trim()
if (-not $explicitTag) {
    $explicitTag = ([string]$env:SUPERFORECASTING_AGENT_RELEASE_TAG).Trim()
}
if (-not $explicitTag) {
    $explicitTag = ([string]$env:TAG).Trim()
}
$tagWasSet = [bool]$explicitTag
$Tag = if ($explicitTag) { $explicitTag } else { "latest" }
if ($Tag -ne "latest" -and $Tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
    Fail "Tag must be latest or strict SemVer (vX.Y.Z)."
}

if (-not $Manifest) {
    $Manifest = ([string]$env:MANIFEST).Trim()
}
$allowUnverifiedValue = ([string]$env:SUPERFORECASTING_AGENT_ALLOW_UNVERIFIED).Trim()
if (-not $allowUnverifiedValue) {
    $allowUnverifiedValue = ([string]$env:ALLOW_UNVERIFIED).Trim()
}
$allowUnverifiedRelease = $AllowUnverified.IsPresent -or $allowUnverifiedValue -eq "1"

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("superforecasting-release-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir | Out-Null

try {
    Write-Host "==> Resolving Superforecasting Agent release ($Tag)..."
    $manifestPin = $null
    if ($Manifest) {
        if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
            Fail "MANIFEST=$Manifest does not exist."
        }
        $manifestPin = Read-ReleaseManifest $Manifest
        if ($tagWasSet -and $Tag -ne "latest" -and $Tag -ne $manifestPin.Tag) {
            Fail "TAG=$Tag conflicts with the manifest pin ($($manifestPin.Tag))."
        }
        $Tag = $manifestPin.Tag
    }

    $api = if ($Tag -eq "latest") {
        "https://api.github.com/repos/$Repo/releases/latest"
    } else {
        "https://api.github.com/repos/$Repo/releases/tags/$([uri]::EscapeDataString($Tag))"
    }
    $release = Invoke-RestMethod -UseBasicParsing -Uri $api
    $wheels = @($release.assets | Where-Object { $_.name -like "*.whl" })
    if ($wheels.Count -ne 1) {
        Fail "Expected exactly one wheel asset; found $($wheels.Count)."
    }
    $sumsAssets = @($release.assets | Where-Object { $_.name -eq "SHA256SUMS" })
    $manifestAssets = @($release.assets | Where-Object { $_.name -eq "release-manifest.json" })
    $wheelAsset = $wheels[0]
    if ([string]$wheelAsset.name -notmatch '^[A-Za-z0-9_.+-]+\.whl$') {
        Fail "Release wheel asset has an invalid filename."
    }

    if (-not $manifestPin -and $manifestAssets.Count -eq 1) {
        $downloadedManifest = Join-Path $tempDir "release-manifest.json"
        Download $manifestAssets[0].browser_download_url $downloadedManifest
        $manifestPin = Read-ReleaseManifest $downloadedManifest
    }
    if ($manifestPin) {
        if ($wheelAsset.name -ne $manifestPin.WheelName) {
            Fail "Release wheel '$($wheelAsset.name)' does not match manifest wheel '$($manifestPin.WheelName)'."
        }
        if ([string]$release.tag_name -ne $manifestPin.Tag) {
            Fail "Release tag '$($release.tag_name)' does not match manifest tag '$($manifestPin.Tag)'."
        }
    }

    $wheelPath = Join-Path $tempDir $wheelAsset.name
    Download $wheelAsset.browser_download_url $wheelPath

    if ($sumsAssets.Count -eq 0) {
        if (-not $allowUnverifiedRelease) {
            Fail "Release $Tag has no SHA256SUMS; refusing an unverified install."
        }
        Write-Warning "Installing without verification because ALLOW_UNVERIFIED=1 was set."
    } elseif ($sumsAssets.Count -ne 1) {
        Fail "Expected exactly one SHA256SUMS asset; found $($sumsAssets.Count)."
    } else {
        $sumsPath = Join-Path $tempDir "SHA256SUMS"
        Download $sumsAssets[0].browser_download_url $sumsPath
        $escapedName = [regex]::Escape([string]$wheelAsset.name)
        $sumLine = Get-Content -LiteralPath $sumsPath | Where-Object {
            $_ -match "^([0-9a-fA-F]{64})\s+\*?$escapedName$"
        } | Select-Object -First 1
        if (-not $sumLine) {
            Fail "SHA256SUMS has no entry for $($wheelAsset.name)."
        }
        $expectedSha = ($sumLine -split '\s+')[0].ToLowerInvariant()
        $actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelPath).Hash.ToLowerInvariant()
        if ($actualSha -ne $expectedSha) {
            Fail "Wheel sha256 mismatch against SHA256SUMS; nothing was installed."
        }
        if ($manifestPin -and $actualSha -ne $manifestPin.WheelSha256) {
            Fail "Wheel sha256 mismatch against release-manifest.json; nothing was installed."
        }
        Write-Host "OK  Wheel sha256 verified."
    }

    if ($VerifyOnly) {
        Write-Host "OK  Release assets verified; installation skipped."
        return
    }

    $python = Find-SupportedPython
    if (-not $python) {
        Fail "Python 3.11-3.13 is required but was not found."
    }
    $pythonExe = $python.Exe
    $pythonArgs = $python.Args

    & $pythonExe @pythonArgs -m pipx --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "==> Installing pipx..."
        & $pythonExe @pythonArgs -m pip install --user --upgrade pipx
        if ($LASTEXITCODE -ne 0) {
            Fail "Could not install pipx."
        }
    }

    Write-Host "==> Installing verified wheel with pipx..."
    & $pythonExe @pythonArgs -m pipx install --force $wheelPath
    if ($LASTEXITCODE -ne 0) {
        Fail "pipx could not install the release wheel."
    }

    $agentHome = ([string]$env:SUPERFORECASTING_AGENT_HOME).Trim()
    if (-not $agentHome) { $agentHome = ([string]$env:FORECAST_HOME).Trim() }
    if (-not $agentHome) { $agentHome = ([string]$env:HERMES_HOME).Trim() }
    if (-not $agentHome) { $agentHome = Join-Path $env:USERPROFILE ".superforecasting-agent" }
    try {
        New-Item -ItemType Directory -Force -Path $agentHome | Out-Null
        Set-Content -LiteralPath (Join-Path $agentHome ".install_method") -Value "release" -Encoding Ascii
    } catch {
        Write-Warning "Could not stamp $agentHome\.install_method."
    }

    $binDir = (& $pythonExe @pythonArgs -m pipx environment --value PIPX_BIN_DIR | Select-Object -Last 1)
    Write-Host ""
    Write-Host "OK  Installed Superforecasting Agent."
    if ($binDir) {
        Write-Host "    Binary directory: $([string]$binDir)"
    }
    Write-Host "    Start the desk: $Binary --tui"
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
