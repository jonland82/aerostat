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
$siteUrl = Get-Output "SiteUrl"

& aws lambda put-function-concurrency --profile $Profile --region $Region --function-name $functionName --reserved-concurrent-executions 1 --no-cli-pager | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not enable Lambda" }

$currentPath = Join-Path $BuildDir "distribution-current.json"
$updatePath = Join-Path $BuildDir "distribution-enabled.json"
$distributionJson = (& aws cloudfront get-distribution-config --profile $Profile --id $distributionId --output json | Out-String)
if ($LASTEXITCODE -ne 0) { throw "Could not read CloudFront distribution" }
Write-Utf8NoBom $currentPath $distributionJson
$current = Get-Content -Raw -LiteralPath $currentPath | ConvertFrom-Json
if (-not $current.DistributionConfig.Enabled) {
    $current.DistributionConfig.Enabled = $true
    Write-Utf8NoBom $updatePath ($current.DistributionConfig | ConvertTo-Json -Depth 100)
    & aws cloudfront update-distribution --profile $Profile --id $distributionId --if-match $current.ETag --distribution-config "file://$updatePath" --no-cli-pager | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not enable CloudFront" }
    & aws cloudfront wait distribution-deployed --profile $Profile --id $distributionId
    if ($LASTEXITCODE -ne 0) { throw "CloudFront did not finish enabling" }
}

& (Join-Path $PSScriptRoot "start-collector.ps1") -Profile $Profile -Region $Region -StackName $StackName
Write-Host "Dashboard started: $siteUrl"
