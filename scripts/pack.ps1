# 打包：只收 MV3 运行需要的 4 个文件，不要把 scripts/docs 打进包里。
# 注意：本文件必须存为 UTF-8 with BOM，否则 PowerShell 5.1 会按 ANSI 解码中文导致解析失败。
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# PowerShell 5.1 的 Get-Content 默认按 ANSI 解码，必须显式指定 UTF8，否则中文 manifest 会被读坏。
$manifest = Get-Content (Join-Path $root "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$version = $manifest.version
$dist = Join-Path $root "dist"
$stage = Join-Path $dist "stage"
$zip = Join-Path $dist ("whisper-ext-" + $version + ".zip")

if (-not (Test-Path $dist)) { New-Item -ItemType Directory -Path $dist -Force | Out-Null }
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

foreach ($f in @("manifest.json", "popup.html", "popup.js", "service_worker.js")) {
    Copy-Item (Join-Path $root $f) (Join-Path $stage $f)
}
if (-not (Test-Path (Join-Path $root "icons"))) { throw "icons 目录缺失，manifest 里的图标会加载失败" }
Copy-Item (Join-Path $root "icons") (Join-Path $stage "icons") -Recurse

# 打包前做静态检查：manifest 引用的文件必须真实存在，避免装上去才发现白屏或缺图标。
$required = @($manifest.background.service_worker, $manifest.action.default_popup)
$required += @($manifest.icons.PSObject.Properties.Value)
$required += @($manifest.action.default_icon.PSObject.Properties.Value)
$missing = @()
foreach ($f in $required) {
    if ([string]::IsNullOrWhiteSpace($f)) { continue }
    if (-not (Test-Path (Join-Path $stage $f))) { $missing += $f }
}
if ($missing.Count -gt 0) { throw ("manifest 引用了不存在的文件: " + ($missing -join ", ")) }
if ($manifest.manifest_version -ne 3) { throw "只发布 MV3" }

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

$size = [math]::Round((Get-Item $zip).Length / 1KB, 1)
$msg = "已打包 " + $zip + "  (" + $size + " KB, v" + $version + ")"
Write-Output $msg
