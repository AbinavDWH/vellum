# Vellum — AI Autonomous Infrastructure & Database Designer

> **Autonomous NLP-driven Cloud Infrastructure & Database Architecture Engine**  
> **LLM Runtime:** LM Studio (Local Inference)  
> **Target Environment:** AWS Cloud (Development, Staging, Production) + PostgreSQL  
> **Status:** Production-Ready Phase 1 Architecture

---

## 🌟 Overview

**Vellum** transforms natural language requirements into fully validated, secure, and production-ready cloud infrastructure and relational database schemas. Built with a strict **Human-in-the-Loop** approval gate and deterministic validation, the LLM proposes designs while deterministic code and human operators govern execution.

```
┌────────────────────────────────────────────────────────┐
│                   VELLUM PIPELINE                      │
├────────────────────────────────────────────────────────┤
│  1. User Requirement (Natural Language)                │
│                         │                              │
│                         ▼                              │
│  2. LM Studio Local AI (Qwen/Llama)                    │
│     → Generates Universal IR (JSON)                    │
│                         │                              │
│                         ▼                              │
│  3. Deterministic Validation & Security Auditor        │
│     → Syntax checks, CIS Benchmark & Risk Analysis     │
│                         │                              │
│                         ▼                              │
│  4. ⚠️ Human-in-the-Loop Approval Gate ⚠️              │
│     → Interactive Topology & Cost Preview              │
│     → [Approve] | [Modify Prompt] | [Reject]          │
│                         │                              │
│                         ▼                              │
│  5. Terraform HCL & SQL DDL Generation                 │
│     → Generates main.tf (AWS Cloud) & schema.sql       │
│                         │                              │
│                         ▼                              │
│  6. Execution & Live Streaming Engine                  │
│     → WebSocket real-time progress                     │
│                         │                              │
│                         ▼                              │
│  7. State Verification, Drift Audit & Hash Logging     │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features & Innovations

1. **Local-First AI with LM Studio**:
   - OpenAI-compatible integration targeting `http://localhost:1234/v1`.
   - Auto-discovers loaded models (`qwen3.5-4b`, `llama-3.1`, etc.).
   - Structured JSON schema enforcement with resilient fallback handling.
2. **Universal Infrastructure Representation (IR)**:
   - Provider-agnostic intermediate format modeling VPCs, Subnets, Databases, Storage, Security Groups, and Relational Schemas.
3. **Human-in-the-Loop Approval Gate**:
   - Categorizes risk: `LOW` 🟢, `MEDIUM` 🟡, `HIGH` 🟠, `CRITICAL` 🔴.
   - For destructive/critical actions, requires operator typing confirmation phrase before execution.
4. **Native AWS Cloud Adapter**:
   - Generates compliant Terraform HCL targeting AWS Cloud environments (`dev`, `staging`, `prod`).
   - Tags all resources with `ManagedBy = "Vellum"`.
5. **PostgreSQL Relational Automation**:
   - Generates clean SQL DDL with primary keys, foreign key constraints, indexes, and extensions.
6. **Execution Engine & WebSocket Live Stream**:
   - Runs Terraform apply with fail-closed credential validation.
   - Live streaming terminal output via WebSockets.
7. **Verification & Drift Detection Engine**:
   - Compares desired state from Universal IR against actual deployed state in AWS Cloud.
8. **Immutable Audit Trail**:
   - Cryptographic SHA-256 hash calculation for every event, payload, and approval decision.
9. **Modern Glassmorphic React UI**:
   - Interactive Architecture Visualizer, Schema Viewer, Cost Estimator, and Real-time Console.

---

## 🛠️ Quick Start

### 1. Prerequisites
- **Python 3.11+**
- **Node.js 18+** & **npm**
- **LM Studio** running locally at `http://localhost:1234/v1`
- **Terraform 1.5+** (Installed in `~/.local/bin/terraform`)
- **AWS Credentials** configured via Vellum Connections Manager (Development, Staging, Production)

### 2. Setup Virtual Environment & Dependencies

```bash
# Python backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Frontend
cd frontend
npm install
npm run build
cd ..
```

### 3. Launching Vellum

#### Option A: Unified Full-Stack Server
FastAPI automatically serves both the REST/WebSocket API and the built React frontend:

```bash
source .venv/bin/activate
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser!

#### Option B: Development Mode (Vite Hot-Reload)
In terminal 1 (Backend):
```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --reload --port 8000
```

In terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```
Open **[http://localhost:3000](http://localhost:3000)**.

---

## 🧪 Verification Checkpoints & Test Suite

All test suites pass verification:

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/ -v
```

| Module | Test File | Status | Checkpoint Criteria |
|---|---|---|---|
| **Module 1** | `test_module_1_lm_studio.py` | ✅ PASSED | LM Studio Chat & JSON Schema inference |
| **Module 2** | `test_module_2_ir_generation.py` | ✅ PASSED | Natural Language to Universal IR parsing |
| **Module 3** | `test_module_3_approval.py` | ✅ PASSED | Human-in-the-Loop approval gate blocking |
| **Module 4** | `test_module_4_terraform.py` | ✅ PASSED | AWS Cloud Terraform HCL generation |
| **Module 5** | `test_module_5_execution.py` | ✅ PASSED | Execution engine with fail-closed credential validation |
| **Module 6** | `test_module_6_verification.py` | ✅ PASSED | State verification & drift detection |
| **Module 7** | `test_module_7_e2e.py` | ✅ PASSED | Complete end-to-end autonomous pipeline |
| **Module 8** | `frontend/` | ✅ PASSED | React + TypeScript + Tailwind UI integration |

---

## 📂 Project Directory Structure

```text
vellum/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app + REST + WebSockets + Static SPA
│   │   ├── config.py                  # Environment settings
│   │   ├── database.py                # Database connection & session setup
│   │   ├── models.py                  # SQLAlchemy metadata models (Plans, Approvals, Audit)
│   │   ├── llm/
│   │   │   ├── client.py              # LM Studio client (local inference)
│   │   │   ├── prompts.py             # System & clarification prompts
│   │   │   └── parser.py              # Robust JSON parser with schema validation
│   │   ├── schemas/
│   │   │   ├── ir.py                  # Universal IR Pydantic models
│   │   │   ├── database.py            # Relational database schemas
│   │   │   ├── cloud.py               # Cloud resources schemas
│   │   │   └── api.py                 # API request/response models
│   │   ├── engines/
│   │   │   ├── orchestrator.py        # Autonomous orchestrator pipeline
│   │   │   ├── terraform_generator.py # AWS Terraform HCL generator
│   │   │   ├── execution_engine.py    # AWS Cloud apply & execution runner
│   │   │   └── verification_engine.py # State verification & drift detection
│   │   ├── approval/
│   │   │   ├── engine.py              # Approval state machine & preview formatter
│   │   │   └── models.py              # Risk levels & approval states
│   │   ├── adapters/
│   │   │   ├── cloud/
│   │   │   │   ├── base.py            # Abstract cloud provider adapter
│   │   │   │   ├── aws.py             # AWS (Native Cloud: dev, staging, prod)
│   │   │   │   └── azure.py           # Azure (Architecture Ready)
│   │   │   └── database/
│   │   │       ├── base.py            # Abstract DB adapter
│   │   │       └── postgresql.py      # PostgreSQL DDL generator & executor
│   │   ├── validation/
│   │   │   ├── syntax.py              # IR syntax & reference validator
│   │   │   ├── security.py            # Security audit benchmark (CIS/IAM/Network)
│   │   │   └── policy.py              # Risk classification & confirmation phrases
│   │   ├── credentials/
│   │   │   └── manager.py             # Cloud credential management & isolation
│   │   └── audit/
│   │       └── logger.py              # Immutable SHA-256 audit logger
│   ├── tests/                         # All Verification Checkpoint tests
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Navbar.tsx             # System status & tabs
│   │   │   ├── Chat/                  # Natural Language input & clarification modal
│   │   │   ├── PlanPreview/           # Topology visualizer, schema viewer & approval
│   │   │   ├── ExecutionProgress/     # Live WebSocket terminal & verification card
│   │   │   └── AuditLog/              # Immutable audit history viewer
│   │   ├── services/api.ts            # Frontend REST client
│   │   ├── types.ts                   # TypeScript interfaces
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── Dockerfile
├── terraform-workspace/               # Isolated per-plan Terraform workspaces
├── scripts/
│   └── setup.sh                       # One-click bootstrap script
├── docker-compose.yml
├── .env
├── PLAN.md
└── README.md
```

---

*Vellum — Empowering developers to build autonomous, reliable, and secure cloud infrastructure with natural language.*
