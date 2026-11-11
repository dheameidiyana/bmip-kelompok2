param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Targets
)

$ErrorActionPreference = "Continue"

$make = (Get-Command make -ErrorAction SilentlyContinue).Source
if (-not $make) {
    $make = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Recurse -Filter make.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $make) {
    throw "GNU Make not found. Install it with: winget install ezwinports.make"
}

$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) {
    throw "Git not found on PATH."
}

$gitRoot = Split-Path (Split-Path $git -Parent) -Parent
$sh = Join-Path $gitRoot "usr\bin\sh.exe"
if (-not (Test-Path -LiteralPath $sh)) {
    throw "Git sh not found at $sh"
}

$env:PATH = "$(Join-Path $gitRoot 'usr\bin');$(Join-Path $gitRoot 'bin');$env:PATH"

$shArg = "SHELL=" + ($sh -replace '\\', '/')
& $make $shArg @Targets
exit $LASTEXITCODE
