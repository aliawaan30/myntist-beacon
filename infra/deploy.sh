#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy Myntist Sovereign Beacon to AWS ECS/Fargate
# Usage: ./infra/deploy.sh [image-tag]
# Requires: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, DATABASE_URL in env

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID env var is required — set it to your 12-digit AWS account ID}"
TAG="${1:-$(date +%Y%m%d%H%M%S)}"
STACK="myntist-beacon"

REPO_API="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/myntist-beacon-api"
REPO_EXPRESS="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/myntist-beacon-express"
REPO_DASHBOARD="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/myntist-beacon-dashboard"

ROOT="$(git rev-parse --show-toplevel)"

echo "==> [1/5] Logging in to ECR"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

echo "==> [2/5] Building images (tag: $TAG)"

# FastAPI backend
docker build -t "$REPO_API:$TAG" -t "$REPO_API:latest" \
  -f "$ROOT/myntist-beacon/Dockerfile.api" \
  "$ROOT/myntist-beacon"

# Express API (build from monorepo root for workspace deps)
docker build -t "$REPO_EXPRESS:$TAG" -t "$REPO_EXPRESS:latest" \
  -f "$ROOT/artifacts/api-server/Dockerfile" \
  "$ROOT"

# React dashboard
docker build -t "$REPO_DASHBOARD:$TAG" -t "$REPO_DASHBOARD:latest" \
  -f "$ROOT/artifacts/beacon-dashboard/Dockerfile" \
  "$ROOT"

echo "==> [3/5] Pushing images to ECR"
docker push "$REPO_API:$TAG"
docker push "$REPO_API:latest"
docker push "$REPO_EXPRESS:$TAG"
docker push "$REPO_EXPRESS:latest"
docker push "$REPO_DASHBOARD:$TAG"
docker push "$REPO_DASHBOARD:latest"

echo "==> [4/5] Pushing secrets to SSM Parameter Store"
put_param() {
  aws ssm put-parameter --region "$REGION" \
    --name "/myntist/beacon/$1" \
    --value "$2" \
    --type SecureString \
    --overwrite \
    --no-cli-pager 2>/dev/null || true
}

put_param "DATABASE_URL"            "${DATABASE_URL}"
put_param "ED25519_PRIVATE_KEY_HEX" "${ED25519_PRIVATE_KEY_HEX}"
put_param "GODADDY_API_KEY"         "${GODADDY_API_KEY:-}"
put_param "GODADDY_API_SECRET"      "${GODADDY_API_SECRET:-}"
put_param "STAGING_SIGNING_KEY"     "${STAGING_SIGNING_KEY:-}"

echo "==> [5/5] Deploying CloudFormation stack: $STACK"

STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" --region "$REGION" \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DOES_NOT_EXIST")

CF_ACTION="create-stack"
if [[ "$STACK_STATUS" != "DOES_NOT_EXIST" ]]; then
  CF_ACTION="update-stack"
fi

aws cloudformation "$CF_ACTION" \
  --stack-name "$STACK" \
  --region "$REGION" \
  --template-body "file://$ROOT/infra/cloudformation.yml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    "ParameterKey=ImageTagApi,ParameterValue=$TAG" \
    "ParameterKey=ImageTagExpress,ParameterValue=$TAG" \
    "ParameterKey=ImageTagDashboard,ParameterValue=$TAG" \
    "ParameterKey=DatabaseUrl,ParameterValue=PLACEHOLDER_RESOLVED_FROM_SSM" \
    "ParameterKey=Ed25519PrivateKeyHex,ParameterValue=PLACEHOLDER_RESOLVED_FROM_SSM" \
    "ParameterKey=GodaddyApiKey,ParameterValue=PLACEHOLDER_RESOLVED_FROM_SSM" \
    "ParameterKey=GodaddyApiSecret,ParameterValue=PLACEHOLDER_RESOLVED_FROM_SSM" \
    "ParameterKey=StagingSigningKey,ParameterValue=PLACEHOLDER_RESOLVED_FROM_SSM" \
  --no-cli-pager

echo "  Waiting for stack to complete (this takes ~3 minutes)..."
aws cloudformation wait "stack-${CF_ACTION%-stack}-complete" \
  --stack-name "$STACK" --region "$REGION"

echo ""
echo "==> Deployment complete!"
aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table \
  --no-cli-pager
