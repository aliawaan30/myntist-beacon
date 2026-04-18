# Architecture

## System Context

```
┌──────────────────────────────────────────────────────────────────────┐
│ External World                                                        │
│                                                                       │
│  Keycloak ──webhook──►  Substrate API  ◄─── REST clients             │
│  GitHub Actions ────►                                                 │
│  Cron/Lambda ──────►                                                  │
└──────────────────────────────────────────────────────────────────────┘
                            │
                  ┌─────────┼──────────┐
                  ▼         ▼          ▼
            PostgreSQL  TimescaleDB  AWS S3
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
  SurvivabilityEngine   FinancialEngine
        │                    │
        └─────────┬──────────┘
                  ▼
          generate_status (Lambda)
                  │
        ┌─────────┼─────────┬──────────┐
        ▼         ▼         ▼          ▼
    S3/CloudFront  GoDaddy DNS  IPFS/Pinata  Zenodo
    (status.json)  (TXT records)  (CID)      (DOI)
```

---

## Mermaid — Full System Diagram

```mermaid
graph TB
    subgraph Ingress
        EXT[External Clients]
        WH[Keycloak Webhooks]
        CI[GitHub Actions / Cron]
    end

    subgraph BeaconAPI["Beacon API  (FastAPI, ECS Fargate :8000)"]
        MAIN[substrate_api/main.py]
        SE[SurvivabilityEngine]
        FE[FinancialEngine]
        PE[PolicyEngine]
        AH[Autoheal / role_decay]
    end

    subgraph Signing
        ED[Ed25519Signer]
        KMS[AWS KMS RSA-PSS]
    end

    subgraph Storage
        PG[(PostgreSQL)]
        TS[(TimescaleDB)]
        S3[(AWS S3)]
        CF[CloudFront CDN]
    end

    subgraph Anchor
        GD[GoDaddy DNS TXT]
        IPFS[IPFS / Pinata]
        ZN[Zenodo]
    end

    subgraph Broadcast
        FC[Farcaster Hub]
        LN[Lens Protocol]
        HSCE[HSCE Endpoint]
    end

    subgraph Dashboard
        UI[React Dashboard :3000]
        EXP[Express API :3001]
    end

    EXT -->|REST / API Key| MAIN
    WH -->|HMAC-signed POST| MAIN
    CI -->|generate_status invoke| MAIN

    MAIN --> SE
    MAIN --> FE
    MAIN --> PE
    MAIN --> AH

    SE --> ED
    FE --> ED
    ED -->|fallback| KMS

    MAIN --> PG
    MAIN --> TS
    SE --> S3
    S3 --> CF

    SE --> GD
    SE --> IPFS
    SE --> ZN

    SE --> FC
    SE --> LN
    SE --> HSCE

    UI -->|API calls| MAIN
    UI --> EXP
    EXP --> MAIN

    AH -->|open PR| GH[GitHub App API]
```

---

## AWS Infrastructure

```mermaid
graph TB
    subgraph VPC
        subgraph PublicSubnets["Public Subnets"]
            ALB[Application Load Balancer]
        end
        subgraph PrivateSubnets["Private Subnets"]
            APITASK[ECS Task: Beacon API\n:8000]
            EXPTASK[ECS Task: Express API\n:3001]
            DASHTASK[ECS Task: Dashboard\n:80]
        end
        IGW[Internet Gateway]
    end

    subgraph AWS
        ECR[ECR Repositories\nmyntist-beacon-api\nmyntist-beacon-express\nmyntist-beacon-dashboard]
        SSM[SSM Parameter Store\n/myntist/beacon/*]
        KMSSVC[AWS KMS\nRSASSA_PSS_SHA_256]
        S3SVC[S3 Bucket\nmyntist-beacon-feeds]
        CF[CloudFront Distribution]
        CW[CloudWatch Logs\n/myntist/beacon]
        CB[CodeBuild Pipeline]
    end

    Internet -->|HTTPS :443| ALB
    ALB -->|/api/*  :8000| APITASK
    ALB -->|/express/* :3001| EXPTASK
    ALB -->|/* :80| DASHTASK

    APITASK -->|pull secrets| SSM
    APITASK -->|sign bytes| KMSSVC
    APITASK -->|write status.json| S3SVC
    S3SVC --> CF
    APITASK --> CW
    EXPTASK --> CW
    DASHTASK --> CW

    CB -->|push images| ECR
    ECR -->|pull images| APITASK
    ECR -->|pull images| EXPTASK
    ECR -->|pull images| DASHTASK

    IGW --> PrivateSubnets
```

---

## Data Flow — Status.json Generation

```mermaid
sequenceDiagram
    participant Trigger as Cron / Manual
    participant Lambda as generate_status handler
    participant DB as PostgreSQL
    participant SE as SurvivabilityEngine
    participant FE as FinancialEngine
    participant Signer as kms_signer
    participant S3
    participant DNS as GoDaddy DNS
    participant IPFS
    participant Zenodo

    Trigger->>Lambda: invoke(event)
    Lambda->>DB: SELECT latest telemetry row
    DB-->>Lambda: S, δS, Q, τ, ∇φ, field_state

    alt No DB data
        Lambda->>SE: compute_survivability(Q, ∇φ, τ)
        SE-->>Lambda: SurvivabilityResult
    end

    Lambda->>FE: compute_all(survival_out, timescale_client)
    FE-->>Lambda: float_yield, liquidity_signal, coherence_signal, r_HSCE

    Lambda->>Lambda: assemble payload dict
    Lambda->>Lambda: SHA-256(canonical JSON bytes) → hash
    Lambda->>Signer: sign_bytes(canonical bytes)
    Signer-->>Lambda: "ed25519:<b64url>" or KMS signature

    Lambda->>S3: PUT api/field/v1/status.json
    Lambda->>IPFS: pin_json(payload)
    IPFS-->>Lambda: CID
    Lambda->>Zenodo: deposit(title, file_content)
    Zenodo-->>Lambda: DOI

    Lambda->>DNS: update_dns_records(_s.v1, _buoy.latest, _float.audit, _ledger.anchor)
    Lambda-->>Trigger: return payload
```

---

## IAM Policy Evaluation Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as Substrate API
    participant PE as PolicyEngine
    participant FE as FinancialEngine
    participant DB

    Client->>API: POST /policy/evaluate {action, context}
    API->>DB: fetch latest telemetry
    DB-->>API: (S, Q, τ, field_state)
    API->>FE: compute_all(telemetry)
    FE-->>API: (D, T_τ, float_yield, ...)
    API->>PE: evaluate(action, field_vector)
    PE->>PE: match policy rules by action
    PE->>PE: check each condition (gt/lt/gte/lte)
    PE-->>API: {admitted: true/false, matched_rule, reasons}
    API-->>Client: 200 {admitted, ...}
```

---

## Signing Architecture

```
ED25519_PRIVATE_KEY_HEX ──► Ed25519PrivateKey.from_private_bytes()
                                     │
                                     ▼
                           .sign(canonical_bytes)
                                     │
                                     ▼
                         "ed25519:<base64url>"   ──► status.json["signature"]

                              FALLBACK PATH
KMS_KEY_ID (real ARN) ──► boto3.client("kms").sign(
                              KeyId, Message, MessageType="RAW",
                              SigningAlgorithm="RSASSA_PSS_SHA_256"
                          )
                                     │
                                     ▼
                         base64(signature_bytes)  ──► status.json["signature"]

Note: KMS_KEY_ID set to an alias/ prefix is intentionally disabled.
      Only a concrete key ARN or key UUID activates KMS signing.
```

---

## Local Service Ports

| Port | Service |
|---|---|
| 5432 | PostgreSQL (primary) |
| 5433 | TimescaleDB |
| 8000 | FastAPI Substrate API |
| 3000 | React Dashboard |
| 3001 | Express API (when running) |

---

## Module Dependency Map

```
generate_status/handler.py
    ├── beacon_core.telemetry.survivability_engine
    ├── beacon_core.telemetry.financial_engine
    ├── beacon_core.telemetry.financial_validator
    ├── beacon_core.telemetry.telemetry_exporter
    ├── beacon_core.signing.kms_signer
    │       └── beacon_core.signing.ed25519_signer
    ├── beacon_core.dns.godaddy_updater
    ├── identity_loop.zenodo.ipfs_pinner
    └── identity_loop.zenodo.zenodo_client

substrate_api/main.py
    ├── iam_substrate.substrate_api.policy_engine
    ├── iam_substrate.substrate_api.role_decay   (autoheal)
    ├── beacon_core.signing.ed25519_signer
    ├── beacon_core.signing.field_signing_keys
    └── beacon_core.hsce.*
```
