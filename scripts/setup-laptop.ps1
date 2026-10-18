<#
.SYNOPSIS
  Set up LegalLens on a second laptop from the team's git repository.
.DESCRIPTION
  Clones the repo (or updates it), creates a Python venv, installs the pinned
  dependencies, downloads the Gemma and embedding models with checksum checks,
  installs the CUDA llama.cpp build, and runs the test suite.
  Models are gitignored, so git cannot carry them; this script fetches them.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-laptop.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-laptop.ps1 -SkipModels
#>
param(
    [string]$Repo = "https://github.com/ZERODAY-2026/TH3_B0Tz.git",
    [string]$Dir = "$env:USERPROFILE\LegalLens",
    [string]$Branch = "main",
    [string]$Tools = "$env:USERPROFILE\LegalLens-tools",
    [switch]$SkipModels
)
$ErrorActionPreference = "Stop"
$LlamaBuild = "b11680"
$GemmaSha   = "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87"
$MiniRev    = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
$MiniSha    = @{ "onnx/model.onnx" = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452";
                 "tokenizer.json"  = "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037" }

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" }
}
function Check-Sha($path, $expected) {
    $got = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $expected) { throw "Checksum mismatch for $path (got $got)" }
    Write-Host "  checksum OK: $(Split-Path $path -Leaf)"
}

Step "Checking tools"
Need git "Install Git for Windows: winget install Git.Git"
Need python "Install Python 3.11+: winget install Python.Python.3.13"
$pyver = (python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ([version]$pyver -lt [version]"3.11") { throw "Python 3.11+ needed, found $pyver" }
Write-Host "  git and Python $pyver found"

Step "Getting the repository ($Branch)"
if (Test-Path "$Dir\.git") {
    git -C $Dir fetch origin
    git -C $Dir checkout $Branch
    git -C $Dir pull --ff-only origin $Branch
} else {
    git clone --branch $Branch $Repo $Dir
}
Set-Location $Dir

Step "Python environment"
if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = Join-Path $Dir ".venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "  created .env from .env.example" }

if (-not $SkipModels) {
    Step "Gemma 4 E4B Q4_K_M (4.98 GB, checksum checked)"
    $gguf = Join-Path $Dir "models\gemma-4-E4B-it-Q4_K_M.gguf"
    if (-not (Test-Path $gguf)) {
        & $py -c "from huggingface_hub import hf_hub_download as d; d('unsloth/gemma-4-E4B-it-GGUF', 'gemma-4-E4B-it-Q4_K_M.gguf', local_dir='models')"
    }
    Check-Sha $gguf $GemmaSha

    Step "Embedding model all-MiniLM-L6-v2 (91 MB, pinned commit)"
    $mini = Join-Path $Dir "models\all-MiniLM-L6-v2"
    & $py -c "from huggingface_hub import hf_hub_download as d; [d('sentence-transformers/all-MiniLM-L6-v2', f, revision='$MiniRev', local_dir=r'$mini') for f in ('onnx/model.onnx', 'tokenizer.json')]"
    foreach ($f in $MiniSha.Keys) { Check-Sha (Join-Path $mini ($f -replace '/', '\')) $MiniSha[$f] }

    Step "llama.cpp $LlamaBuild, CUDA build (needs an NVIDIA GPU and driver 580+)"
    $llama = Join-Path $Tools "llama-cpp-cuda"
    if (-not (Test-Path (Join-Path $llama "llama-server.exe"))) {
        New-Item -ItemType Directory -Force -Path $llama | Out-Null
        $base = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaBuild"
        foreach ($zip in "llama-$LlamaBuild-bin-win-cuda-13.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip") {
            $out = Join-Path $Tools $zip
            Invoke-WebRequest -Uri "$base/$zip" -OutFile $out
            Expand-Archive -Path $out -DestinationPath $llama -Force
        }
    }
    & (Join-Path $llama "llama-server.exe") --version
}

Step "Running the tests (no model or network needed)"
& $py -m pytest tests -q

Step "Done"
Write-Host "Start the model server in its own terminal:"
Write-Host "  $llama\llama-server.exe -m `"$gguf`" --host 127.0.0.1 --port 8080 -c 8192 -ngl 99 --jinja --chat-template-kwargs `"{\`"enable_thinking\`":false}`""
Write-Host "Then, in this folder:"
Write-Host "  .venv\Scripts\activate"
Write-Host "  python smoke.py --file data\samples\rental_clear.pdf"
Write-Host "CPU-only laptop: leave out -ngl 99 and set GEMMA_TIMEOUT=900 in .env."
