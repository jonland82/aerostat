param(
    [string]$Profile = "default",
    [string]$Region = "us-east-1",
    [string]$StackName = "opensky-dashboard"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StaticPath = Join-Path $Root "static"

function Get-Output([string]$Key) {
    $value = & aws cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue | [0]" --output text
    if ($LASTEXITCODE -ne 0) { throw "Could not read stack $StackName" }
    return ($value | Out-String).Trim()
}

$bucket = Get-Output "StaticBucketName"
$distributionId = Get-Output "DistributionId"
$siteUrl = Get-Output "SiteUrl"

& aws s3 sync $StaticPath "s3://$bucket" --profile $Profile --region $Region --delete --cache-control "no-cache" --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Static upload failed" }
$invalidationJson = (& aws cloudfront create-invalidation --profile $Profile --distribution-id $distributionId --paths "/*" --no-cli-pager --output json | Out-String)
if ($LASTEXITCODE -ne 0) { throw "CloudFront invalidation failed" }
$invalidationId = ($invalidationJson | ConvertFrom-Json).Invalidation.Id
& aws cloudfront wait invalidation-completed --profile $Profile --distribution-id $distributionId --id $invalidationId
if ($LASTEXITCODE -ne 0) { throw "CloudFront invalidation did not complete" }

Write-Host "Frontend published: $siteUrl"
