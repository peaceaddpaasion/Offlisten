# 单向同步：本仓库（事实源）-> 主项目 whisper/extension（内测加载副本）。
# 禁止反向手改主项目副本；那边改了会在下次同步时被覆盖。
# 注意：本文件必须存为 UTF-8 with BOM，否则 PowerShell 5.1 会按 ANSI 解码中文导致解析失败。
param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($Target)) {
    $Target = Join-Path (Split-Path -Parent $root) "whisper\extension"
}

if (-not (Test-Path $Target)) { throw ("目标目录不存在: " + $Target) }

$files = @("manifest.json", "popup.html", "popup.js", "service_worker.js")
$changed = New-Object System.Collections.ArrayList
$same = 0

foreach ($f in $files) {
    $src = Join-Path $root $f
    $dst = Join-Path $Target $f
    if (-not (Test-Path $src)) { throw ("源文件缺失: " + $src) }
    if (Test-Path $dst) {
        $a = (Get-FileHash $src -Algorithm SHA256).Hash
        $b = (Get-FileHash $dst -Algorithm SHA256).Hash
        if ($a -eq $b) { $same++; continue }
    }
    Copy-Item $src $dst -Force
    [void]$changed.Add($f)
}

Write-Output ("同步到 " + $Target)
if ($changed.Count -gt 0) {
    Write-Output ("  未变 " + $same + " 个; 覆盖 " + $changed.Count + " 个: " + ($changed -join ", "))
} else {
    Write-Output ("  未变 " + $same + " 个; 无覆盖")
}
Write-Output "  提示: 已加载的 unpacked 扩展需要在扩展管理页点一次「重新加载」才会生效。"
