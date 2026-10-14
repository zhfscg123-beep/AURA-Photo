param([Parameter(Mandatory=$true)][string]$AppDir)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$WorkRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'work'))
$ResolvedApp = (Resolve-Path -LiteralPath $AppDir).Path
if (-not $ResolvedApp.StartsWith($WorkRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build only inside work/' }
$Compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
Push-Location -LiteralPath $ResolvedApp
try {
    & $Compiler /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll '/win32icon:assets/aura.ico' '/out:AURA Photo.exe' source/Launcher.cs
    if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
} finally { Pop-Location }
