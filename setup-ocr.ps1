$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Test-Path -LiteralPath 'backend/.ocr-venv/Scripts/python.exe')) {
    uv venv --python 3.12 backend/.ocr-venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python 3.12 environment.' }
}
uv pip install --python backend/.ocr-venv/Scripts/python.exe -r backend/requirements-ocr-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'OCR dependencies were not installed.' }
Write-Output 'Local OCR is ready. Models are bundled; runtime requires no cloud OCR.'
