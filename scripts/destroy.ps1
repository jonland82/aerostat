param(
    [string]$Profile = "default",
    [string]$Region = "us-east-1",
    [string]$StackName = "opensky-dashboard",
    [switch]$KeepCredentials,
    [switch]$KeepLocalConfig
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-Output([string]$Key) {
    $value = & aws cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue | [0]" --output text
    if ($LASTEXITCODE -ne 0) { throw "Could not read stack $StackName" }
    return ($value | Out-String).Trim()
}

$accountId = (& aws sts get-caller-identity --profile $Profile --query Account --output text | Out-String).Trim()
$artifactBucket = "$StackName-artifacts-$accountId-$Region".ToLowerInvariant()
$staticBucket = Get-Output "StaticBucketName"
$dataBucket = Get-Output "DataBucketName"

& (Join-Path $PSScriptRoot "stop.ps1") -Profile $Profile -Region $Region -StackName $StackName

& aws s3 rm "s3://$staticBucket" --recursive --profile $Profile --region $Region --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Could not empty static bucket" }
& aws s3 rm "s3://$dataBucket" --recursive --profile $Profile --region $Region --only-show-errors
if ($LASTEXITCODE -ne 0) { throw "Could not empty data bucket" }

& aws cloudformation delete-stack --profile $Profile --region $Region --stack-name $StackName
if ($LASTEXITCODE -ne 0) { throw "Could not start stack deletion" }
& aws cloudformation wait stack-delete-complete --profile $Profile --region $Region --stack-name $StackName
if ($LASTEXITCODE -ne 0) { throw "Stack deletion did not complete" }

if (-not $KeepCredentials) {
    & aws secretsmanager delete-secret --profile $Profile --region $Region --secret-id "/$StackName/opensky" --force-delete-without-recovery --no-cli-pager | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not delete OpenSky secret" }
}

& aws s3 rm "s3://$artifactBucket" --recursive --profile $Profile --region $Region --only-show-errors
if ($LASTEXITCODE -eq 0) {
    & aws s3api delete-bucket --profile $Profile --region $Region --bucket $artifactBucket
}

$localConfigPath = Join-Path $Root "deploy.local.json"
if (-not $KeepLocalConfig -and (Test-Path -LiteralPath $localConfigPath)) {
    Remove-Item -LiteralPath $localConfigPath -Force
}

Write-Host "Dashboard AWS resources removed."
