# One-command setup on Windows. Usage (PowerShell, in the project folder):
#   .\setup.ps1                                   # full live setup (GPU or CPU PyTorch picked automatically)
#   .\setup.ps1 --keys sigil-proving-keys.zip     # also install the shipped proving keys
#   .\setup.ps1 --minimal                         # demo UI with saved results only (installs nothing)
# All options: python scripts\setup_env.py --help
$ErrorActionPreference = "Stop"
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $py = @("py", "-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = @("python") }
else { Write-Error "Python 3.10+ is required: install it from https://www.python.org/downloads/ and re-run."; exit 1 }
& $py[0] $py[1..($py.Length - 1)] "$PSScriptRoot\scripts\setup_env.py" @args
exit $LASTEXITCODE
