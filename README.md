# Myntist Sovereign Beacon

A sovereign-grade telemetry and IAM beacon that continuously computes, signs, and broadcasts the health state of the Myntist identity field. The beacon produces a cryptographically signed `status.json` anchored to DNS, IPFS, and Zenodo, and enforces temporal IAM policies derived from live field measurements.

---

## Repository Layout

```
myntist-fixed/
├── myntist-beacon/                  Main Python monorepo
│   ├── beacon_core/                 Core computation and I/O
│   │   ├── dns/                     GoDaddy DNS anchoring
│   │   ├── hsce/                    HSCE push client
│   │   ├── lambdas/generate_status/ Lambda: build + sign status.json
│   │   ├── signing/                 Ed25519 + KMS signing primitives
│   │   └── telemetry/               SurvivabilityEngine, FinancialEngine
│   ├── dashboard/                   React + Vite operator dashboard
│   ├── iam_substrate/               IAM substrate service
│   │   ├── ledger/                  Audit ledger
│   │   ├── policies/                Policy YAML definitions
│   │   ├── substrate_api/           FastAPI service (main entry point)
│   │   └── webhooks/                HMAC-authenticated webhook receivers
│   ├── identity_loop/               Decentralised broadcast and anchoring
│   │   ├── feeds/                   Farcaster + Lens adapters
│   │   ├── well_known/              /.well-known document builders
│   │   └── zenodo/                  IPFS pin + Zenodo deposit clients
│   ├── kcp/                         Key Continuity Protocol verifier
│   ├── monitoring/grafana/          Grafana dashboard JSON
│   ├── scripts/                     Seed, demo, and audit scripts
│   ├── tests/                       Pytest test suite
│   ├── .github/workflows/           CI/CD pipelines
│   ├── docker-compose.yml           Local development stack
│   ├── Dockerfile.api               FastAPI container build
│   └── .env.example                 Full environment variable reference
├── artifacts/
│   └── api-server/                  Express.js API artifact
├── infra/
│   ├── cloudformation.yml           AWS ECS/Fargate stack definition
│   ├── deploy.sh                    Manual deploy script
│   └── buildspec.yml                AWS CodeBuild pipeline spec
└── lib/                             Shared TypeScript libraries
```

---

## Core Concepts

### Survivability Score — S(t)

The primary field health metric, computed by `SurvivabilityEngine`:

```
S(t) = (1 / Q(t)) × cos(∇φ(t)) × τ(t)
```

| Symbol | Meaning |
|---|---|
| `Q` | Coherence quality (higher = healthier) |
| `∇φ` | Phase gradient (deviation from equilibrium) |
| `τ` | Temporal continuity factor |
| `S` | Normalised survivability in [0, 1] |
| `δS` | First derivative of S (rate of change) |

### Phase 2 Financial Signals

`FinancialEngine` computes six additional fields added in schema version 2.0:

| Field | Description |
|---|---|
| `float_yield` | Net float yield after OPEX |
| `liquidity_signal` (D) | Liquidity depth metric |
| `coherence_signal` (T_τ) | Temporal coherence signal |
| `r_HSCE` | Rolling HSCE return (R-window smoothed) |
| `float_reinvestment_rate` | Reinvestment fraction of float yield |

### Signed status.json

Every beacon pulse produces a `status.json` containing all of the above plus:

- `hash` — SHA-256 of the canonical JSON bytes
- `signature` — `"ed25519:<base64url>"` when `ED25519_PRIVATE_KEY_HEX` is set, or base64 KMS RSASSA_PSS_SHA_256 if only `KMS_KEY_ID` is set
- `url` — the canonical public URL (set via `CANONICAL_URL`)

The file is written to S3 at `api/field/v1/status.json` and served via CloudFront.

### Signing Priority

```
ED25519_PRIVATE_KEY_HEX set  →  Ed25519 (preferred, fastest)
KMS_KEY_ID set (real ARN)    →  KMS RSASSA_PSS_SHA_256 (production fallback)
Neither                      →  signature field omitted, warning logged
```

HMAC-SHA256 is used only for internal webhook authentication headers — never for public beacon signatures.

### DNS Anchoring

Four GoDaddy TXT records are updated on every `generate_status` invocation:

| Record | Content |
|---|---|
| `_s.v1.myntist.com` | Live survivability data (`S`, `δS`, `Q`, `τ`) |
| `_buoy.latest.myntist.com` | Canonical status URL + payload hash |
| `_float.audit.myntist.com` | Float analytics (`float_yield`, `coherence_signal`) |
| `_ledger.anchor.myntist.com` | IPFS CID + Zenodo DOI (when credentials set) |

### Temporal IAM Policies

`PolicyEngine` evaluates YAML policy rules against the current field state vector `(S, Q, τ, D, T_τ)`. Policies use operators (`gt`, `lt`, `gte`, `lte`) against field thresholds. An action is admitted only when all conditions in the applicable rule pass.

### Autoheal

`role_decay.check_and_heal()` queries the IAM substrate for flagged identities and, when decay thresholds are exceeded, opens a GitHub Pull Request via the GitHub App API. Required env vars: `GH_APP_ID`, `GH_APP_PRIVATE_KEY`, `GH_APP_INSTALLATION_ID`, `GH_APP_REPO`. Runs on a cron schedule via `.github/workflows/autoheal_detect.yml`.

### Key Continuity Protocol (KCP)

The `kcp/` module verifies seven continuity invariants over the signing key history log (no timestamp gaps, monotonic chain, recomputable hashes). Run `kcp.continuity_verifier.verify()` after any key rotation.

---

## Quick Start — Local Development

**Prerequisites:** Docker Desktop, Python 3.11+, Node 20+

```bash
# 1. Clone and enter the beacon directory
cd myntist-beacon

# 2. Copy and edit the env file
cp .env.example .env
# At minimum set: DATABASE_URL, ED25519_PRIVATE_KEY_HEX, CANONICAL_URL

# 3. Start the full stack (Postgres + TimescaleDB + FastAPI + Dashboard)
docker compose up --build

# 4. Seed the database
python scripts/seed.py

# 5. Verify the API is running
curl http://localhost:8000/health
curl http://localhost:8000/field/v1/status.json
```

Dashboard: http://localhost:3000
API docs: http://localhost:8000/docs

---

## Running Tests

```bash
cd myntist-beacon
pip install -r requirements.txt
pytest tests/ -v
```

---

## Environment Variables

See `.env.example` for the full reference with descriptions. Critical variables:

| Variable | Required | Notes |
|---|---|---|
| `AWS_ACCOUNT_ID` | Deploy only | 12-digit AWS account ID |
| `AWS_REGION` | Deploy only | Default `us-east-1` |
| `CANONICAL_URL` | Production | Full URL of `/api/field/v1/status.json` |
| `ED25519_PRIVATE_KEY_HEX` | Signing | 32-byte hex Ed25519 private key |
| `DATABASE_URL` | Always | PostgreSQL connection string |
| `GODADDY_API_KEY` / `GODADDY_API_SECRET` | DNS anchoring | Both required for DNS updates |
| `GH_APP_ID` / `GH_APP_PRIVATE_KEY` / `GH_APP_INSTALLATION_ID` / `GH_APP_REPO` | Autoheal | All four required |

---

## Architecture Overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed diagrams.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step AWS deployment instructions.

## Runbooks

See [RUNBOOKS.md](RUNBOOKS.md) for operational procedures.
