# 微信云托管 CLI 包装脚本：绕过 npm 全局 shim 在 mise 环境下的路径问题
# 用法：pwsh -File .\deploy\cloudrun\wxcloud.ps1 login
#      pwsh -File .\deploy\cloudrun\wxcloud.ps1 env:list
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

$ErrorActionPreference = 'Stop'

$candidates = @(
  'C:\Users\许昀\.local\share\mise\installs\node\24.21.0\node_modules\@wxcloud\cli\bin\run'
)

try {
  $root = (npm root -g 2>$null)
  if ($root) { $candidates += (Join-Path $root.Trim() '@wxcloud\cli\bin\run') }
} catch { }

$cli = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $cli) {
  throw "未找到 @wxcloud/cli，请先执行：npm install -g @wxcloud/cli"
}

$nodeCandidates = @(
  'C:\Users\许昀\.local\share\mise\installs\node\24.21.0\node.exe',
  (Join-Path $env:ProgramFiles 'nodejs\node.exe')
)
$node = $nodeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $node) {
  $found = (Get-Command node -ErrorAction SilentlyContinue)
  if ($found) { $node = $found.Source }
}
if (-not $node) { throw '未找到 node.exe' }

& $node $cli @Args
exit $LASTEXITCODE
