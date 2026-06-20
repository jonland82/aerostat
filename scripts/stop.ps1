param(
    [string]$Profile = "default",
    [string]$Region = "us-east-1",
    [string]$StackName = "opensky-dashboard"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildDir = Join-Path $Root ".aws-build"
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding($false)))
}

function Get-Output([string]$Key) {
    $value = & aws cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue | [0]" --output text
    if ($LASTEXITCODE -ne 0) { throw "Could not read stack $StackName" }
    return ($value | Out-String).Trim()
}

$functionName = Get-Output "FunctionName"
$distributionId = Get-Output "DistributionId"

& (Join-Path $PSScriptRoot "stop-collector.ps1")
& aws lambda put-function-concurrency --profile $Profile --region $Region --function-name $functionName --reserved-concurrent-executions 0 --no-cli-pager | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not stop Lambda" }

$currentPath = Join-Path $BuildDir "distribution-current.json"
$updatePath = Join-Path $BuildDir "distribution-disabled.json"
$distributionJson = (& aws cloudfront get-distribution-config --profile $Profile --id $distributionId --output json | Out-String)
if ($LASTEXITCODE -ne 0) { throw "Could not read CloudFront distribution" }
Write-Utf8NoBom $currentPath $distributionJson
$current = Get-Content -Raw -LiteralPath $currentPath | ConvertFrom-Json
if ($current.DistributionConfig.Enabled) {
    $current.DistributionConfig.Enabled = $false
    Write-Utf8NoBom $updatePath ($current.DistributionConfig | ConvertTo-Json -Depth 100)
    & aws cloudfront update-distribution --profile $Profile --id $distributionId --if-match $current.ETag --distribution-config "file://$updatePath" --no-cli-pager | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not disable CloudFront" }
    & aws cloudfront wait distribution-deployed --profile $Profile --id $distributionId
    if ($LASTEXITCODE -ne 0) { throw "CloudFront did not finish disabling" }
}

Write-Host "Dashboard stopped: Lambda concurrency is 0 and CloudFront is disabled."
