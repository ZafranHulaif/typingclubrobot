# Bungkus folder Release Flutter jadi satu TypingBot.exe (pembawa + zip + ekor).
# pakai: pack.ps1 -Launcher <TypingBotSetup.exe> -AppDir <Release> -Version 4.0.0 -Out <TypingBot.exe>
param([string]$Launcher, [string]$AppDir, [string]$Version, [string]$Out)
$ErrorActionPreference = 'Stop'
# runtime VC++ ikut dibawa (PC tanpa redist tetap jalan)
foreach ($dll in 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') {
  $src = Join-Path $env:SystemRoot "System32\$dll"
  if ((Test-Path $src) -and -not (Test-Path (Join-Path $AppDir $dll))) { Copy-Item $src $AppDir }
}
$zip = Join-Path ([IO.Path]::GetTempPath()) "tb-app-$([guid]::NewGuid()).zip"
Compress-Archive -Path (Join-Path $AppDir '*') -DestinationPath $zip -CompressionLevel Optimal
$exe = [IO.File]::ReadAllBytes($Launcher)
$z = [IO.File]::ReadAllBytes($zip)
$v = [Text.Encoding]::UTF8.GetBytes($Version)
$fs = [IO.File]::Create($Out)
$fs.Write($exe, 0, $exe.Length)
$fs.Write($z, 0, $z.Length)
$fs.Write($v, 0, $v.Length)
$fs.Write([BitConverter]::GetBytes([uint32]$v.Length), 0, 4)
$fs.Write([BitConverter]::GetBytes([uint64]$z.Length), 0, 8)
$magic = [Text.Encoding]::ASCII.GetBytes('TBBNDL01')
$fs.Write($magic, 0, 8)
$fs.Close()
Remove-Item $zip
Write-Host "bundel $Out ($([math]::Round((Get-Item $Out).Length / 1MB, 1)) MB), versi $Version"
