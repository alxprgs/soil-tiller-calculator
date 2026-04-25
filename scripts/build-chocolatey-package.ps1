[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Version,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $ReleaseTag,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string] $Checksum64,

    [ValidateNotNullOrEmpty()]
    [string] $OutputDirectory = (Join-Path $PSScriptRoot '..\dist\chocolatey')
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = Join-Path $repoRoot 'chocolatey'
$buildRoot = Join-Path $repoRoot 'build\chocolatey'
$packageRoot = Join-Path $buildRoot 'soil-tiller-calculator'
$toolsRoot = Join-Path $packageRoot 'tools'

if (Test-Path $packageRoot) {
    Remove-Item -LiteralPath $packageRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$nuspecSource = Join-Path $sourceRoot 'soil-tiller-calculator.nuspec'
$nuspecPath = Join-Path $packageRoot 'soil-tiller-calculator.nuspec'
Copy-Item -LiteralPath $nuspecSource -Destination $nuspecPath

$installTemplatePath = Join-Path $sourceRoot 'tools\chocolateyInstall.ps1.template'
$installScriptPath = Join-Path $toolsRoot 'chocolateyInstall.ps1'
$installScript = (Get-Content -LiteralPath $installTemplatePath -Raw -Encoding UTF8).
    Replace('{{RELEASE_TAG}}', $ReleaseTag).
    Replace('{{CHECKSUM64}}', $Checksum64.ToLowerInvariant())

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($installScriptPath, $installScript, $utf8NoBom)

$uninstallTemplatePath = Join-Path $sourceRoot 'tools\chocolateyUninstall.ps1.template'
$uninstallScriptPath = Join-Path $toolsRoot 'chocolateyUninstall.ps1'
$uninstallScript = Get-Content -LiteralPath $uninstallTemplatePath -Raw -Encoding UTF8
[System.IO.File]::WriteAllText($uninstallScriptPath, $uninstallScript, $utf8NoBom)

& choco pack $nuspecPath --version $Version --outputdirectory $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "choco pack failed with exit code $LASTEXITCODE."
}

$packagePath = Join-Path $OutputDirectory "soil-tiller-calculator.$Version.nupkg"
if (-not (Test-Path $packagePath)) {
    throw "Expected package was not created: $packagePath"
}

Write-Output $packagePath
