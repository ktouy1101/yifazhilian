# 一条命令部署到云托管（登录 CLI 后使用）
# 用法示例：
#   pwsh -File .\deploy\cloudrun\deploy.ps1 `
#     -EnvId prod-d7gck81ghb168ec59 -ServiceName flask-iiym `
#     -DbUrl "mysql://root:密码@10.20.103.25:3306/yifazhilian" `
#     -AdminPhone 19077411124
param(
  [Parameter(Mandatory = $true)][string]$EnvId,
  [Parameter(Mandatory = $true)][string]$ServiceName,
  [string]$DbUrl = '',
  [string]$AdminPhone = '',
  [string]$Region = 'ap-shanghai',
  [string]$Dockerfile = 'deploy/cloudrun/Dockerfile',
  [int]$Port = 80
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$pairs = @(
  'YIFAZHILIAN_ALLOWED_HOSTS=*',
  'YIFAZHILIAN_RUNTIME_MODE=production',
  'YIFAZHILIAN_DEMO_AUTH=1'
)
if ($AdminPhone) { $pairs += "YIFAZHILIAN_ADMIN_PHONE=$AdminPhone" }
if ($DbUrl) { $pairs += "YIFAZHILIAN_DB_URL=$DbUrl" }

$envParams = ($pairs -join '&')

Write-Host '本次部署参数：' -ForegroundColor Cyan
Write-Host "  环境      : $EnvId ($Region)"
Write-Host "  服务      : $ServiceName"
Write-Host "  端口      : $Port"
Write-Host "  Dockerfile: $Dockerfile"
Write-Host "  环境变量  : $($pairs -replace 'YIFAZHILIAN_DB_URL=.*', 'YIFAZHILIAN_DB_URL=***' | Out-String)"
Write-Host ''

& "$PSScriptRoot\wxcloud.ps1" run:deploy . `
  --envId $EnvId `
  --serviceName $ServiceName `
  --region $Region `
  --targetDir . `
  --dockerfile $Dockerfile `
  --containerPort $Port `
  --envParams $envParams `
  --remark 'yifazhilian backend' `
  --noConfirm

exit $LASTEXITCODE
