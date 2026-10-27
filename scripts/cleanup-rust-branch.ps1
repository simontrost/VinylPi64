# Run from the repository root on branch refactor/rust.
# Removes ONLY Git-tracked legacy Python sources and Python tests.
# Does NOT delete data/, assets/, web/, vendor/, .build-tools/, or target/.
$ErrorActionPreference = 'Stop'
if (-not (Test-Path 'Cargo.toml') -or -not (Test-Path 'src/main.rs')) {
    throw 'Run this script in the VinylPi64 Rust repository root.'
}
$branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'refactor/rust') {
    throw "Expected branch refactor/rust; current branch: '$branch'"
}
$files = @(git ls-files -- vinylpi tests requirements.txt | Where-Object {
    $_ -eq 'requirements.txt' -or
    $_ -like 'vinylpi/*' -or
    ($_ -like 'tests/*' -and $_ -match '\.py$')
})
if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
foreach ($f in $files) {
    git rm --quiet -- "$f"
    if ($LASTEXITCODE -ne 0) { throw "Failed to remove tracked file: $f" }
}
Write-Host "Removed $($files.Count) tracked Python files. Rust tests and assets remain." -ForegroundColor Green
Write-Host 'Temporary local caches can be deleted separately; DO NOT delete .build-tools while Cargo lives there.'
Write-Host 'Review: git status --short'
