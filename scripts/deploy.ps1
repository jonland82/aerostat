param(
    [string]$Profile = "default",
    [string]$Region = "us-east-1",
    [string]$StackName = "opensky-dashboard",
    [switch]$RotateAdminKey,
    [switch]$RotateOriginKey
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildDir = Join-Path $Root ".aws-build"
$CredentialsPath = Join-Path $Root "credentials.json"
$LocalConfigPath = Join-Path $Root "deploy.local.json"
$TemplatePath = Join-Path $Root "infrastructure\template.yaml"
$LambdaPath = Join-Path $Root "aws\lambda_function.py"
$StaticPath = Join-Path $Root "static"
$ResultsPath = Join-Path $Root "experiments\global-state-series\visualizations"
$NotesPath = Join-Path $Root "experiments\global-state-series\notes"

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & aws @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed. Review the service error above."
    }
}

function Get-AwsText {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $result = & aws @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed. Review the service error above."
    }
    return ($result | Out-String).Trim()
}

function New-RandomKey([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-Sha256([string]$Value) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding($false)))
}

if (-not (Test-Path -LiteralPath $CredentialsPath)) {
    throw "Missing $CredentialsPath"
}

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$identity = Get-AwsText sts get-caller-identity --profile $Profile --region $Region --output json
$accountId = ($identity | ConvertFrom-Json).Account
$artifactBucket = "$StackName-artifacts-$accountId-$Region".ToLowerInvariant()

if (Test-Path -LiteralPath $LocalConfigPath) {
    $localConfig = Get-Content -Raw -LiteralPath $LocalConfigPath | ConvertFrom-Json
} else {
    $localConfig = [pscustomobject]@{
        adminRefreshKey = New-RandomKey
        originVerify = New-RandomKey
    }
}
if ($RotateAdminKey) {
    $localConfig.adminRefreshKey = New-RandomKey
}
if ($RotateOriginKey) {
    $localConfig.originVerify = New-RandomKey
}
Write-Utf8NoBom $LocalConfigPath ($localConfig | ConvertTo-Json)
$adminHash = Get-Sha256 $localConfig.adminRefreshKey

$secretName = "/$StackName/opensky"
$secretArn = Get-AwsText secretsmanager list-secrets --profile $Profile --region $Region --query "SecretList[?Name=='$secretName'].ARN | [0]" --output text
if (-not $secretArn -or $secretArn -eq "None") {
    $secretArn = Get-AwsText secretsmanager create-secret --profile $Profile --region $Region --name $secretName --description "OpenSky OAuth client credentials for Aerostat" --secret-string "file://$CredentialsPath" --query ARN --output text
} else {
    Invoke-Aws secretsmanager put-secret-value --profile $Profile --region $Region --secret-id $secretArn --secret-string "file://$CredentialsPath" --no-cli-pager | Out-Null
}

$existingBucket = Get-AwsText s3api list-buckets --profile $Profile --query "Buckets[?Name=='$artifactBucket'].Name | [0]" --output text
if (-not $existingBucket -or $existingBucket -eq "None") {
    if ($Region -eq "us-east-1") {
        Invoke-Aws s3api create-bucket --profile $Profile --region $Region --bucket $artifactBucket --no-cli-pager | Out-Null
    } else {
        Invoke-Aws s3api create-bucket --profile $Profile --region $Region --bucket $artifactBucket --create-bucket-configuration "LocationConstraint=$Region" --no-cli-pager | Out-Null
    }
    Invoke-Aws s3api put-public-access-block --profile $Profile --region $Region --bucket $artifactBucket --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    $encryptionPath = Join-Path $BuildDir "artifact-encryption.json"
    Write-Utf8NoBom $encryptionPath '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
    Invoke-Aws s3api put-bucket-encryption --profile $Profile --region $Region --bucket $artifactBucket --server-side-encryption-configuration "file://$encryptionPath"
}

$zipPath = Join-Path $BuildDir "lambda.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $LambdaPath -DestinationPath $zipPath -CompressionLevel Optimal
$codeHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$codeKey = "lambda/$codeHash.zip"
Invoke-Aws s3 cp $zipPath "s3://$artifactBucket/$codeKey" --profile $Profile --region $Region --only-show-errors

Invoke-Aws cloudformation deploy `
    --profile $Profile `
    --region $Region `
    --stack-name $StackName `
    --template-file $TemplatePath `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset `
    --parameter-overrides `
        "ArtifactBucket=$artifactBucket" `
        "LambdaCodeKey=$codeKey" `
        "OpenSkySecretArn=$secretArn" `
        "AdminKeyHash=$adminHash" `
        "OriginVerify=$($localConfig.originVerify)" `
    --no-cli-pager

$staticBucket = Get-AwsText cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='StaticBucketName'].OutputValue | [0]" --output text
$distributionId = Get-AwsText cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue | [0]" --output text
$siteUrl = Get-AwsText cloudformation describe-stacks --profile $Profile --region $Region --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue | [0]" --output text

Invoke-Aws s3 sync $StaticPath "s3://$staticBucket" --profile $Profile --region $Region --delete --exclude "experiment-results/*" --exclude "experiment-notes/*" --cache-control "no-cache" --only-show-errors
Invoke-Aws s3 sync $ResultsPath "s3://$staticBucket/experiment-results" --profile $Profile --region $Region --delete --exclude "build_data.py" --cache-control "no-cache" --only-show-errors
Invoke-Aws s3 sync $NotesPath "s3://$staticBucket/experiment-notes" --profile $Profile --region $Region --delete --exclude "*" --include "*.pdf" --cache-control "no-cache" --only-show-errors
Invoke-Aws cloudfront create-invalidation --profile $Profile --distribution-id $distributionId --paths "/*" --no-cli-pager | Out-Null
& (Join-Path $PSScriptRoot "start-collector.ps1") -Profile $Profile -Region $Region -StackName $StackName

Write-Host ""
Write-Host "Deployment complete: $siteUrl"
Write-Host "Owner refresh key: $LocalConfigPath"
Write-Host "The collector calls OpenSky only after the site's Refresh aircraft button is used."
