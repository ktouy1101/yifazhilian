# 交互式登录窗口：在新终端里运行，供用户手动输入 AppID 与 AppSecret
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
Write-Host '=== 微信云托管登录 ===' -ForegroundColor Cyan
Write-Host 'AppID : wx9e74331f354e3d4c'
Write-Host '秘钥  : 粘贴 AppSecret（公众平台 → 开发管理 → 开发设置）' -ForegroundColor Yellow
Write-Host ''
& "$PSScriptRoot\wxcloud.ps1" login
Write-Host ''
Write-Host '登录结束后可以关闭本窗口（成功会显示 登录成功）' -ForegroundColor Green
Read-Host '按回车关闭'
