# AWS Deployment and Operations

This runbook covers the Aerostat AWS architecture, credentials, deployment, shutdown, restart, credential rotation, troubleshooting, and complete removal.

## Architecture

```text
Browser
  |
CloudFront (the only public entry point)
  |-- private S3 static bucket: HTML, CSS, JavaScript, globe assets
  |-- private S3 data bucket: compressed latest aircraft snapshot
  `-- API Gateway HTTP API
        `-- Lambda (reserved concurrency: 1)
              |-- DynamoDB: atomic cooldown and daily credit ledger
              `-- SQS FIFO queue
                    `-- local collector on this workstation
                          |-- Secrets Manager: OpenSky OAuth credentials
                          `-- OpenSky REST API
```

CloudFront injects a private origin-verification header before API requests. Direct calls to the API Gateway hostname are rejected. Snapshot reads are public through CloudFront. Refresh requires a separate owner key that is entered into the browser and retained only in `sessionStorage` for that tab.

OpenSky currently times out connections from AWS Lambda, consistent with OpenSky's warning that AWS address ranges may be blocked. The local collector is therefore the egress bridge: it waits on SQS and contacts OpenSky only after an authenticated owner click. This computer must be running the collector for the deployed Refresh button to complete.

There is no EventBridge schedule, OpenSky polling schedule, WebSocket, or periodic browser aircraft refresh. Opening the deployed site does not request OpenSky data. The short status checks made after an explicit refresh click query only AWS and stop when that request finishes.

## AWS Credentials

The deployment commands default to:

- CLI profile: `default`
- Region: `us-east-1`
- Stack: `opensky-dashboard`

Use a dedicated IAM role or user with only the permissions required to manage this stack. Do not deploy with AWS account root credentials. The scripts accept a named CLI profile so credentials remain outside the repository.

Validate the deployment identity before every material operation:

```powershell
aws sts get-caller-identity --profile default
aws configure get region --profile default
```

To use another AWS profile or region:

```powershell
.\scripts\deploy.ps1 -Profile another-profile -Region us-west-2
```

AWS CLI credentials live outside this repository under `%USERPROFILE%\.aws`. Never add them to project files or paste them into source code.

## Application Secrets

### OpenSky OAuth credentials

Create the local file from the committed placeholder:

```powershell
Copy-Item credentials.example.json credentials.json
```

Then replace the placeholders so `credentials.json` contains:

```json
{
  "clientId": "...",
  "clientSecret": "..."
}
```

The deploy script uploads that JSON to the AWS Secrets Manager secret `/opensky-dashboard/opensky`. The local collector reads the secret at runtime through the selected AWS CLI profile. The file is gitignored.

To change OpenSky credentials:

1. Replace the values in local `credentials.json`.
2. Run `.\scripts\deploy.ps1` again.
3. The script creates a new Secrets Manager version without exposing values through CloudFormation.

OpenSky access tokens are temporary and live only for a collector request.

### Owner refresh key

The first deployment generates a random owner key in local `deploy.local.json`. That file is gitignored. Enter `adminRefreshKey` when the deployed site prompts during manual refresh. The browser retains it only for the current tab session.

Rotate it with:

```powershell
.\scripts\deploy.ps1 -RotateAdminKey
```

Close any browser tabs holding the old key after rotation.

`deploy.local.json` also contains the CloudFront-to-API origin-verification value. Do not publish this file. Deleting the file and redeploying rotates both values.

Rotate only the origin-verification value with:

```powershell
.\scripts\deploy.ps1 -RotateOriginKey
```

## Deploy or Update

From the repository root:

```powershell
.\scripts\deploy.ps1
```

The script:

1. Verifies the AWS identity.
2. Creates or updates the OpenSky secret.
3. Creates a private deployment-artifact bucket.
4. Packages and uploads Lambda.
5. Creates or updates the CloudFormation stack.
6. Uploads the static website to its private bucket.
7. Invalidates CloudFront.
8. Starts the local SQS collector in a hidden process.

CloudFront creation or modification commonly takes several minutes. Re-running the command is the normal update workflow.

For HTML, CSS, JavaScript, or vendored asset changes that do not modify AWS infrastructure or Lambda, use the faster static-only path:

```powershell
.\scripts\push-site.ps1
```

It syncs `static/` to the existing private bucket and creates a CloudFront invalidation. It does not package Lambda, update CloudFormation, restart the collector, or call OpenSky.

To retrieve the site URL later:

```powershell
aws cloudformation describe-stacks `
  --stack-name opensky-dashboard `
  --region us-east-1 `
  --profile default `
  --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue | [0]" `
  --output text
```

## Credit Protection

- Global manual refresh cost: four OpenSky state credits.
- Local AWS daily ceiling: 3,000 state credits per UTC day.
- OpenSky standard allowance at deployment time: 4,000 state credits daily.
- Lambda reserved concurrency: one.
- SQS FIFO queue: one manual request stream with five-minute deduplication.
- API Gateway burst limit: two; sustained limit: one request per second.
- DynamoDB obtains an atomic refresh lock and enforces the cooldown.
- The local collector makes no OpenSky call until it receives an owner-requested queue message.
- Only successful OpenSky responses update the snapshot.
- OpenSky's `X-Rate-Limit-Remaining` value is recorded when available.

Changing these controls requires updating `infrastructure/template.yaml` and redeploying. Do not introduce client-side `setInterval()` polling.

## Emergency Shutdown

The supported command is:

```powershell
.\scripts\stop.ps1
```

It stops the local collector, sets Lambda reserved concurrency to zero, and then disables CloudFront. It waits for CloudFront deployment to finish.

### Shutdown in the AWS Console

1. Run `.\scripts\stop-collector.ps1` on this workstation, or stop its `collector.py --watch` process.
2. Open **Lambda**, select the stack's dashboard function, then choose **Configuration > Concurrency > Edit**. Set reserved concurrency to `0`.
3. Open **CloudFront > Distributions**, select the Aerostat distribution, and choose **Disable**.
4. Wait until CloudFront reports the updated deployment state.

The S3 buckets block all public access, so disabling CloudFront removes public website access. Setting Lambda concurrency to zero independently disables the backend even while CloudFront propagates.

## Restart

```powershell
.\scripts\start.ps1
```

This restores Lambda reserved concurrency to one, enables CloudFront, starts the local collector, and waits for deployment. The last S3 snapshot and DynamoDB quota record remain intact across stop/start.

The collector can be controlled independently:

```powershell
.\scripts\start-collector.ps1
.\scripts\stop-collector.ps1
```

Its PID and logs are stored under the gitignored `data/` directory.

## Complete Removal

```powershell
.\scripts\destroy.ps1
```

Destruction performs these operations in order:

1. Stops the local collector and Lambda, then disables CloudFront.
2. Empties the private static and data buckets.
3. Deletes the CloudFormation stack and waits for completion.
4. Permanently deletes the OpenSky Secrets Manager secret without a recovery window.
5. Empties and deletes the deployment-artifact bucket.
6. Deletes local `deploy.local.json`.

Preserve credentials or local configuration when needed:

```powershell
.\scripts\destroy.ps1 -KeepCredentials -KeepLocalConfig
```

`credentials.json` is never deleted by the script.

### Manual removal in the AWS Console

1. Follow the console shutdown procedure above.
2. Empty the stack's two S3 buckets.
3. Open **CloudFormation > Stacks**, select `opensky-dashboard`, and choose **Delete**.
4. Delete `/opensky-dashboard/opensky` from Secrets Manager.
5. Empty and delete `opensky-dashboard-artifacts-<account>-<region>` from S3.

## Logs and Diagnostics

Lambda logs are retained for 14 days under `/aws/lambda/<function-name>` in CloudWatch Logs. The stack also creates a CloudWatch alarm when Lambda records an error.

Local collector output is written to `data/collector.log`; errors are written to `data/collector-error.log`.

Useful commands:

```powershell
aws cloudformation describe-stack-events --stack-name opensky-dashboard --profile default --region us-east-1
aws logs tail /aws/lambda/<function-name> --since 30m --profile default --region us-east-1
aws lambda get-function-concurrency --function-name <function-name> --profile default --region us-east-1
```

If refresh stays at `WAITING FOR COLLECTOR`, confirm `data/collector.pid` identifies a running process and inspect both collector logs. Restart it with `.\scripts\start-collector.ps1`.

## Cost Controls

The stack uses on-demand Lambda, API Gateway, SQS, DynamoDB, S3, and CloudFront rather than an always-running AWS server. Costs should remain low for personal manual use, but they are not guaranteed to be zero.

Create an AWS Budget in **Billing and Cost Management > Budgets** for the account. CloudFront, S3 transfer, excessive public reads, and retained data are the primary areas to monitor. The initial system stores only the latest snapshot; historical analytics storage is not enabled.

## Custom Domain

The initial deployment uses the generated CloudFront domain. A custom domain later requires:

1. A Route 53 hosted zone or external DNS access.
2. An ACM certificate in `us-east-1` for CloudFront.
3. CloudFront aliases and the certificate ARN in CloudFormation.
4. A Route 53 alias record pointing at the distribution.

Do not point DNS directly to the S3 or API Gateway origins.
