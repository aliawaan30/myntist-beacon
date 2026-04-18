# Runbooks

Operational procedures for the Myntist Sovereign Beacon. Each section covers symptoms, diagnosis, and resolution.

---

## Table of Contents

1. [Rotating the Ed25519 Signing Key](#1-rotating-the-ed25519-signing-key)
2. [DNS Anchoring Failure](#2-dns-anchoring-failure)
3. [status.json Not Updating](#3-statusjson-not-updating)
4. [Autoheal PRs Not Being Created](#4-autoheal-prs-not-being-created)
5. [ECS Task Crash / Service Unhealthy](#5-ecs-task-crash--service-unhealthy)
6. [CloudFormation Stack Stuck in UPDATE_ROLLBACK_FAILED](#6-cloudformation-stack-stuck-in-update_rollback_failed)
7. [Survivability Score S Drops to Zero](#7-survivability-score-s-drops-to-zero)
8. [Financial Validation Errors in Logs](#8-financial-validation-errors-in-logs)
9. [IPFS or Zenodo Anchor Failing](#9-ipfs-or-zenodo-anchor-failing)
10. [Key Continuity Protocol (KCP) Verification Failure](#10-key-continuity-protocol-kcp-verification-failure)
11. [Database Connection Lost](#11-database-connection-lost)
12. [Redeploying a Single Service Without Full Stack Update](#12-redeploying-a-single-service-without-full-stack-update)

---

## 1. Rotating the Ed25519 Signing Key

**When:** Key compromise, scheduled rotation, or key expiry (`ED25519_KEY_CREATED` + 1 year).

**Steps:**

```bash
# 1. Generate a new key
python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import binascii, datetime
k = Ed25519PrivateKey.generate()
print('KEY:', binascii.hexlify(k.private_bytes_raw()).decode())
print('CREATED:', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))
"

# 2. Update SSM with the new key
aws ssm put-parameter \
  --name "/myntist/beacon/ED25519_PRIVATE_KEY_HEX" \
  --value "<new-64-char-hex>" \
  --type SecureString \
  --overwrite \
  --region us-east-1

# 3. Update .env or trigger a new deploy so the running task picks up the new key
./infra/deploy.sh

# 4. Run KCP verification to ensure continuity
python3 -c "
import sys; sys.path.insert(0, 'myntist-beacon')
from kcp.continuity_verifier import verify
result = verify()
print(result)
"

# 5. Confirm the well-known document shows the new public key
curl https://<alb-dns>/.well-known/field-signing-keys.json | python3 -m json.tool
```

**Note:** Update `ED25519_KEY_CREATED` to today's date whenever you rotate. The `/.well-known/field-signing-keys.json` endpoint derives the `expires` field from `created + 1 year`.

---

## 2. DNS Anchoring Failure

**Symptom:** Logs contain `DNS update failed (non-fatal)` or TXT records are stale.

**Diagnosis:**

```bash
# Check GoDaddy API key is set
aws ssm get-parameter --name "/myntist/beacon/GODADDY_API_KEY" --with-decryption --query Parameter.Value

# Check current TXT records
dig +short TXT _s.v1.myntist.com
dig +short TXT _buoy.latest.myntist.com
dig +short TXT _float.audit.myntist.com
dig +short TXT _ledger.anchor.myntist.com

# Check application logs for GoDaddy errors
aws logs filter-log-events \
  --log-group-name /myntist/beacon \
  --filter-pattern "godaddy" \
  --region us-east-1 | jq '.events[].message'
```

**Resolution:**

1. Confirm `GODADDY_API_KEY` and `GODADDY_API_SECRET` are both set and not expired (GoDaddy keys expire after 90 days by default).
2. Check `GODADDY_DOMAIN` matches the domain where TXT records should be written.
3. To disable DNS updates temporarily (e.g. during testing): set `ENABLE_DNS_UPDATE=false` and redeploy.
4. To manually trigger an update, invoke `generate_status` directly:

```bash
python3 -c "
import sys; sys.path.insert(0, 'myntist-beacon')
from beacon_core.lambdas.generate_status.handler import handler
result = handler({}, None)
print(result)
"
```

---

## 3. status.json Not Updating

**Symptom:** `generated_at` timestamp in status.json is stale; `feeds_fresh: false`.

**Diagnosis:**

```bash
# Check S3 last-modified
aws s3 ls s3://<bucket>/api/field/v1/status.json --region us-east-1

# Check if there is telemetry in the DB
psql "$DATABASE_URL" -c "SELECT recorded_at, S, field_state FROM telemetry ORDER BY recorded_at DESC LIMIT 5;"
```

**Resolution:**

| Cause | Fix |
|---|---|
| No telemetry rows in DB | Run `python scripts/seed.py` to populate seed data, or trigger `/score` endpoint |
| Lambda/cron not firing | Verify the scheduled event or workflow trigger is enabled |
| S3_BUCKET not set | Set `S3_BUCKET` env var — without it, output goes to `/tmp` only |
| `feeds_fresh: false` | DB returned no rows; Lambda fell back to event parameters |

---

## 4. Autoheal PRs Not Being Created

**Symptom:** Flagged identities accumulate but no GitHub PR is opened; logs show `autoheal: PR creation skipped`.

**Diagnosis:**

```bash
# Check all four required vars are present
for var in GH_APP_ID GH_APP_PRIVATE_KEY GH_APP_INSTALLATION_ID GH_APP_REPO; do
  echo -n "$var: "
  aws ssm get-parameter --name "/myntist/beacon/$var" --region us-east-1 \
    --query Parameter.Name --output text 2>/dev/null || echo "MISSING"
done

# Check GitHub Actions workflow logs
# Go to: github.com/<org>/<repo>/actions → Autoheal Detection
```

**Resolution:**

1. `GH_APP_INSTALLATION_ID` and `GH_APP_REPO` are the most commonly missing variables — they were not in the original codebase and must be added to both the GitHub Actions workflow secrets and SSM.
2. Confirm the GitHub App is installed on the target repository and the installation ID matches.
3. Confirm the App has `contents: write` and `pull_requests: write` permissions on the target repo.
4. Test manually:

```bash
export GH_APP_ID=<id>
export GH_APP_PRIVATE_KEY="$(cat /path/to/key.pem)"
export GH_APP_INSTALLATION_ID=<installation-id>
export GH_APP_REPO=org/repo
export DATABASE_URL=<url>

cd myntist-beacon
python3 -c "
from iam_substrate.substrate_api.role_decay import check_and_heal
check_and_heal()
"
```

---

## 5. ECS Task Crash / Service Unhealthy

**Symptom:** ECS service shows `STOPPED` tasks; ALB health checks failing.

**Diagnosis:**

```bash
# Get the ECS cluster name
aws ecs list-clusters --region us-east-1

# List failed tasks
aws ecs list-tasks \
  --cluster myntist-beacon \
  --desired-status STOPPED \
  --region us-east-1

# Get stop reason for a specific task
aws ecs describe-tasks \
  --cluster myntist-beacon \
  --tasks <task-arn> \
  --region us-east-1 \
  --query 'tasks[0].{stopCode:stopCode,stoppedReason:stoppedReason,containers:containers[*].{name:name,exitCode:exitCode,reason:reason}}'

# Tail recent CloudWatch logs
aws logs tail /myntist/beacon --follow --region us-east-1
```

**Common causes:**

| Exit Code | Cause | Fix |
|---|---|---|
| 1 | Missing env var / import error | Check CloudWatch for the traceback; verify SSM params |
| 137 | OOM kill | Increase `Memory` in CloudFormation task definition |
| 143 | SIGTERM (normal stop during rolling deploy) | Expected — no action needed |

**Restarting a service:**

```bash
aws ecs update-service \
  --cluster myntist-beacon \
  --service myntist-beacon-api \
  --force-new-deployment \
  --region us-east-1
```

---

## 6. CloudFormation Stack Stuck in UPDATE_ROLLBACK_FAILED

**Symptom:** Stack is in `UPDATE_ROLLBACK_FAILED` state; no updates possible.

**Resolution:**

```bash
# 1. Continue rollback (skip the resources that failed to rollback)
aws cloudformation continue-update-rollback \
  --stack-name myntist-beacon \
  --region us-east-1 \
  --resources-to-skip <FailedResourceLogicalId>

# 2. Wait for rollback to complete
aws cloudformation wait stack-rollback-complete \
  --stack-name myntist-beacon \
  --region us-east-1

# 3. Fix the root cause, then redeploy
./infra/deploy.sh
```

If the stack cannot be recovered, delete and recreate:

```bash
aws cloudformation delete-stack --stack-name myntist-beacon --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name myntist-beacon --region us-east-1
./infra/deploy.sh
```

---

## 7. Survivability Score S Drops to Zero

**Symptom:** `field_state` = `"critical"` or `"dead"`; `S` = 0 or very small.

**Diagnosis — check the field state vector:**

```bash
curl https://<alb-dns>/field/v1/status.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for k in ['S','delta_S','Q','tau','nabla_phi','field_state']:
    print(f'{k}: {d.get(k)}')
"

# Check the most recent telemetry rows
curl https://<alb-dns>/telemetry/latest | python3 -m json.tool
```

**Interpretation:**

| Condition | Meaning |
|---|---|
| `Q` >> 1 | Very low coherence — check event ingestion |
| `∇φ` near π/2 | Phase gradient at maximum — field is diverging |
| `τ` → 0 | Temporal continuity broken — check KCP and key chain |
| `S` = 0 exactly | Arithmetic underflow — Q is infinite or τ is 0 |

**Recovery:**

1. Post a normalising event to `/events` to update telemetry
2. If `τ` is the cause, run the KCP verifier (see runbook 10)
3. If the issue is spurious (e.g. test data), post corrected values via `/score`

---

## 8. Financial Validation Errors in Logs

**Symptom:** Logs contain `generate_status: financial validation failed`.

**Diagnosis:**

```bash
aws logs filter-log-events \
  --log-group-name /myntist/beacon \
  --filter-pattern "financial validation failed" \
  --region us-east-1 | jq '.events[].message'
```

The `FinancialValidator` checks that all six Phase 2 fields are present and within expected ranges. Common causes:

| Error | Cause |
|---|---|
| `float_yield out of range` | `OPEX_BASELINE_USD` exceeds gross float |
| `r_HSCE missing` | `TIMESCALEDB_URL` not set so rolling average cannot be computed |
| `coherence_signal NaN` | Zero telemetry rows in TimescaleDB |

**Fix:** Set `TIMESCALEDB_URL` and ensure at least `R_HSCE_SMOOTHING_WINDOW` rows exist in TimescaleDB before production use. Financial validation errors are logged but non-fatal — the beacon continues to publish.

---

## 9. IPFS or Zenodo Anchor Failing

**Symptom:** `_ledger.anchor` TXT record is empty or stale; logs show `IPFS anchor failed` or `Zenodo deposit failed`.

**Diagnosis:**

```bash
aws logs filter-log-events \
  --log-group-name /myntist/beacon \
  --filter-pattern "IPFS\|Zenodo\|anchor" \
  --region us-east-1 | jq '.events[].message'
```

**Resolution:**

| Cause | Fix |
|---|---|
| `IPFS_API_KEY` not set | Add to SSM and redeploy |
| `ZENODO_API_KEY` not set | Add to SSM and redeploy |
| Zenodo sandbox mode | Set `ZENODO_SANDBOX=false` for real deposits |
| Rate limit | Zenodo free tier: 100 deposits/day |

To disable ledger anchoring without disabling DNS updates:

```bash
ENABLE_LEDGER_ANCHOR=false
```

---

## 10. Key Continuity Protocol (KCP) Verification Failure

**Symptom:** `kcp.continuity_verifier.verify()` returns errors; `τ` has dropped.

**Run the verifier:**

```bash
cd myntist-beacon
python3 -c "
import sys; sys.path.insert(0, '.')
from kcp.continuity_verifier import verify
result = verify()
for k, v in result.items():
    print(f'{k}: {v}')
"
```

**KCP invariants checked:**

1. No timestamp gaps in the key history chain
2. Monotonically increasing timestamps
3. Hash chain: each entry's hash is recomputable from its content
4. No duplicate entries
5. Public key is derivable from stored private key
6. `created` date is not in the future
7. Key chain length >= 1

**Recovery steps:**

1. If a gap exists: locate the missing log entries in backups and re-insert
2. If hashes don't match: the key log has been tampered with — escalate immediately
3. After any key rotation, re-run the verifier to confirm `τ` will recover

---

## 11. Database Connection Lost

**Symptom:** API returns 500 errors; logs contain `sqlalchemy.exc.OperationalError`.

**Diagnosis:**

```bash
# Test the connection string directly
psql "$DATABASE_URL" -c "SELECT 1;"

# Check ECS task has network access to the DB
aws ecs describe-tasks --cluster myntist-beacon --tasks <task-arn> \
  --query 'tasks[0].attachments[0].details'
```

**Resolution:**

1. Verify security group rules allow port 5432 inbound from the ECS task security group
2. If using RDS, confirm the RDS instance is in the same VPC as the ECS tasks
3. Confirm `DATABASE_URL` in SSM matches the current DB hostname (hostnames change after RDS failover)
4. Update SSM if the connection string has changed, then force a new ECS deployment:

```bash
aws ssm put-parameter \
  --name "/myntist/beacon/DATABASE_URL" \
  --value "<new-connection-string>" \
  --type SecureString --overwrite --region us-east-1

aws ecs update-service --cluster myntist-beacon \
  --service myntist-beacon-api --force-new-deployment --region us-east-1
```

---

## 12. Redeploying a Single Service Without Full Stack Update

When you only need to push a new image for one service (e.g., a hotfix to the API only):

```bash
export AWS_ACCOUNT_ID=<account-id>
export AWS_REGION=us-east-1
TAG=$(date +%Y%m%d%H%M%S)

# Build and push only the API image
REPO_API="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/myntist-beacon-api"
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -t "$REPO_API:$TAG" -t "$REPO_API:latest" \
  -f myntist-beacon/Dockerfile.api myntist-beacon/
docker push "$REPO_API:$TAG"
docker push "$REPO_API:latest"

# Update just the ImageTagApi parameter in CloudFormation
aws cloudformation update-stack \
  --stack-name myntist-beacon \
  --use-previous-template \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    "ParameterKey=ImageTagApi,ParameterValue=$TAG" \
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
  --region "$AWS_REGION"

aws cloudformation wait stack-update-complete \
  --stack-name myntist-beacon --region "$AWS_REGION"
```
