# Deployment Guide

## Overview

Myntist Beacon deploys to **AWS ECS Fargate** via a CloudFormation stack. Three Docker images are built, pushed to ECR, and run as Fargate services behind an Application Load Balancer.

| Service | Image | Port |
|---|---|---|
| FastAPI Beacon API | `myntist-beacon-api` | 8000 |
| Express API | `myntist-beacon-express` | 3001 |
| React Dashboard | `myntist-beacon-dashboard` | 80 |

---

## Prerequisites

- AWS CLI v2 configured (`aws configure`)
- Docker Desktop running
- Git access to this repository
- The following AWS resources already exist in your account:
  - A VPC with at least two subnets (private or public with IGW route)
  - An Internet Gateway attached to the VPC
  - ECR repositories created (see step 1 below)
  - An S3 bucket for beacon feeds
  - (Optional) A KMS key for RSA-PSS signing

---

## Step 1 — Create ECR Repositories (first time only)

```bash
export AWS_ACCOUNT_ID=<your-12-digit-account-id>
export AWS_REGION=us-east-1

for repo in myntist-beacon-api myntist-beacon-express myntist-beacon-dashboard; do
  aws ecr create-repository --repository-name "$repo" --region "$AWS_REGION" || true
done
```

---

## Step 2 — Provision Secrets in SSM Parameter Store (first time only)

All secrets are stored under `/myntist/beacon/` in SSM. The deploy script pushes them automatically, but you can also set them manually:

```bash
put_param() {
  aws ssm put-parameter \
    --name "/myntist/beacon/$1" \
    --value "$2" \
    --type SecureString \
    --overwrite \
    --region "$AWS_REGION"
}

put_param "DATABASE_URL"            "postgresql://user:pass@host:5432/iam_substrate"
put_param "ED25519_PRIVATE_KEY_HEX" "<64-char hex string>"
put_param "GODADDY_API_KEY"         "<godaddy-key>"
put_param "GODADDY_API_SECRET"      "<godaddy-secret>"
put_param "STAGING_SIGNING_KEY"     "<optional>"
```

To generate a new Ed25519 key:

```bash
python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import binascii
k = Ed25519PrivateKey.generate()
print(binascii.hexlify(k.private_bytes_raw()).decode())
"
```

---

## Step 3 — Set Required Environment Variables

```bash
export AWS_ACCOUNT_ID=<your-12-digit-account-id>
export AWS_REGION=us-east-1
export DATABASE_URL=postgresql://user:pass@host:5432/iam_substrate
export ED25519_PRIVATE_KEY_HEX=<64-char hex>
export CANONICAL_URL=https://yourdomain.com/api/field/v1/status.json
export GODADDY_API_KEY=<key>
export GODADDY_API_SECRET=<secret>
```

---

## Step 4 — Run the Deploy Script

```bash
cd myntist-fixed

# Deploy with an auto-generated timestamp tag
./infra/deploy.sh

# Or specify a tag explicitly
./infra/deploy.sh 20260418120000
```

The script performs five steps:

1. **ECR login** — authenticates Docker to ECR
2. **Build images** — builds all three Docker images
3. **Push images** — pushes both `latest` and tagged versions to ECR
4. **SSM secrets** — uploads all secrets to SSM Parameter Store
5. **CloudFormation** — creates or updates the `myntist-beacon` stack and waits for completion

Expected duration: **3–5 minutes** for a stack update, **5–8 minutes** for initial creation.

---

## Step 5 — Supply CloudFormation Parameters

The CloudFormation template requires VPC/subnet parameters that have no defaults. You must supply them either via the CLI or through the AWS Console.

| Parameter | Description |
|---|---|
| `VpcId` | Your VPC ID (e.g. `vpc-xxxxxxxxxxxxxxxxx`) |
| `Subnets` | Comma-separated subnet IDs |
| `PrivateSubnetRouteTableId` | Route table ID for the private subnets |
| `InternetGatewayId` | Internet Gateway ID already attached to the VPC |
| `DatabaseUrl` | PostgreSQL connection string |
| `Ed25519PrivateKeyHex` | 32-byte Ed25519 private key as hex |
| `GodaddyApiKey` | GoDaddy API key |
| `GodaddyApiSecret` | GoDaddy API secret |
| `GodaddyDomain` | Default `myntist.com` |

If supplying via CLI (rather than the deploy script), add `ParameterKey=VpcId,ParameterValue=vpc-xxx` etc. to the `aws cloudformation create-stack` call.

---

## AWS CodeBuild (CI/CD Pipeline)

`infra/buildspec.yml` runs the same build/push/deploy sequence automatically. To use it:

1. Create a CodeBuild project pointing at this repository
2. Set the following environment variables in the CodeBuild project:
   - `AWS_DEFAULT_REGION`
   - `ACCOUNT_ID` (your 12-digit AWS account ID)
3. Grant the CodeBuild service role permissions to:
   - Push to ECR (`ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, etc.)
   - Write to SSM (`ssm:PutParameter`)
   - Deploy CloudFormation (`cloudformation:CreateStack`, `cloudformation:UpdateStack`, `iam:PassRole`)
4. Secrets are pulled automatically from SSM via the `env.parameter-store` block at the top of `buildspec.yml`

The GitHub Actions workflow (`.github/workflows/deploy.yml`) runs tests and builds on every push to `main`, but delegates the actual deploy to CodeBuild or the `deploy.sh` script.

---

## Verifying Deployment

After the stack completes:

```bash
# Get the ALB DNS name
aws cloudformation describe-stacks \
  --stack-name myntist-beacon \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table

# Health check
curl https://<alb-dns>/health

# Signed status.json
curl https://<alb-dns>/api/field/v1/status.json | python3 -m json.tool

# Signing keys document
curl https://<alb-dns>/.well-known/field-signing-keys.json
```

---

## Updating a Running Stack

To deploy new code without changing infrastructure:

```bash
./infra/deploy.sh   # builds new images, pushes, updates ECS task definitions
```

ECS performs a rolling update — old tasks stay running until new tasks pass health checks.

---

## Rolling Back

To roll back to a previous image tag:

```bash
aws cloudformation update-stack \
  --stack-name myntist-beacon \
  --use-previous-template \
  --parameters \
    "ParameterKey=ImageTagApi,ParameterValue=<previous-tag>" \
    "ParameterKey=ImageTagExpress,UsePreviousValue=true" \
    "ParameterKey=ImageTagDashboard,UsePreviousValue=true" \
    "ParameterKey=VpcId,UsePreviousValue=true" \
    "ParameterKey=Subnets,UsePreviousValue=true" \
    "ParameterKey=DatabaseUrl,UsePreviousValue=true" \
    "ParameterKey=Ed25519PrivateKeyHex,UsePreviousValue=true" \
    "ParameterKey=GodaddyApiKey,UsePreviousValue=true" \
    "ParameterKey=GodaddyApiSecret,UsePreviousValue=true" \
    "ParameterKey=StagingSigningKey,UsePreviousValue=true" \
    "ParameterKey=PrivateSubnetRouteTableId,UsePreviousValue=true" \
    "ParameterKey=InternetGatewayId,UsePreviousValue=true" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

---

## Tearing Down

```bash
aws cloudformation delete-stack --stack-name myntist-beacon --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name myntist-beacon --region us-east-1
```

ECR images and SSM parameters are not deleted automatically. Remove them manually if needed.
