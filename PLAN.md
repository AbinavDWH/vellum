Here is the updated development guide and modular implementation plan, fully rebranded to **Vellum**.

```markdown
# Vellum — AI Development Guide

> **Project:** Vellum (AI-Driven NLP Autonomous Infrastructure Designer)
> **Document Type:** AI Working Specification & Development Plan
> **LLM Runtime:** LM Studio (Local)
> **Current Target:** AWS (via LocalStack)
> **Future Target:** Azure, GCP, OCI
> **Last Updated:** October 04, 2026

---

## 📋 Table of Contents

1. [Project Mission](#1-project-mission)
2. [Current Phase Scope](#2-current-phase-scope)
3. [Technology Stack](#3-technology-stack)
4. [LM Studio Integration](#4-lm-studio-integration)
5. [Human-in-the-Loop Workflow](#5-human-in-the-loop-workflow)
6. [Multi-Cloud Architecture (AWS + Azure Ready)](#6-multi-cloud-architecture)
7. [LocalStack Setup & Configuration](#7-localstack-setup--configuration)
8. [Module-Based Development Plan](#8-module-based-development-plan)
9. [Verification Checkpoints](#9-verification-checkpoints)
10. [Code Templates](#10-code-templates)
11. [Rules for AI Assistant](#11-rules-for-ai-assistant)

---

## 1. Project Mission

Build an AI-driven platform where a developer describes infrastructure in **natural language**, and the system:

1. **Understands** the requirement (via LM Studio local LLM)
2. **Plans** a validated infrastructure design (Universal IR)
3. **Presents** the plan for **human approval** (Human-in-the-Loop)
4. **Generates** Terraform HCL or SQL
5. **Executes** against a cloud provider (currently AWS via LocalStack)
6. **Verifies** the result and logs everything

### Core Principles

| Principle | Rule |
|-----------|------|
| **LLM ≠ Authority** | The LLM suggests. Deterministic code decides. |
| **Human-in-the-Loop** | Nothing executes without explicit human approval. |
| **Credential Isolation** | The LLM never sees passwords, keys, or tokens. |
| **Provider Agnostic** | Core logic works for AWS, Azure, GCP. Adapters handle differences. |
| **Local-First Testing** | All development uses LocalStack. No real cloud costs. |

---

## 2. Current Phase Scope

### ✅ In Scope (Build Now)

| Feature | Status |
|---------|--------|
| LM Studio as LLM backend | 🔨 Active |
| Natural language → Universal IR | 🔨 Active |
| Human-in-the-loop approval gate | 🔨 Active |
| AWS Terraform generation | 🔨 Active |
| LocalStack local execution | 🔨 Active |
| PostgreSQL local database automation | 🔨 Active |
| Verification & audit logging | 🔨 Active |

### 🔮 Designed But Not Built Yet (Architecture Ready)

| Feature | Status |
|---------|--------|
| Azure Terraform generation | 📐 Designed |
| GCP Terraform generation | 📐 Designed |
| MongoDB / MySQL adapters | 📐 Designed |
| Multi-region deployment | 📐 Designed |
| Cost estimation engine | 📐 Designed |

### ❌ Out of Scope

| Feature | Reason |
|---------|--------|
| Real AWS billing/execution | Use LocalStack only for now |
| Kubernetes / EKS | Too complex for Phase 1 |
| LLM fine-tuning | Use base models via LM Studio |
| Multi-tenant SaaS | Single-user local tool for now |

---

## 3. Technology Stack

### Backend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.11+ | Core backend |
| Web Framework | FastAPI | Latest | REST API + WebSocket |
| Database ORM | SQLAlchemy | 2.x | Metadata storage |
| Task Queue | Celery + Redis | Latest | Background execution |
| **LLM Runtime** | **LM Studio** | **Latest** | **Local model inference** |
| IaC Tool | Terraform | 1.5+ | Infrastructure generation |
| Cloud Mock | **LocalStack** | **Latest** | **AWS simulation** |
| Cloud SDK | boto3 | Latest | AWS API interaction |

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | React 18 + TypeScript | UI |
| Styling | Tailwind CSS + shadcn/ui | Components |
| State | Zustand | Client state |
| Real-time | WebSocket (Socket.IO) | Live execution updates |
| Code View | Monaco Editor | Show generated TF/SQL |

### AI / LLM

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Runtime** | **LM Studio** | **Local LLM serving** |
| **API** | **OpenAI-compatible** | **`http://localhost:1234/v1`** |
| **Model (Recommended)** | **Qwen 2.5 Coder 7B** or **Llama 3.1 8B** | **Planning + reasoning** |
| Structured Output | JSON mode / function calling | IR generation |
| Prompt Templates | Jinja2 or Python f-strings | Dynamic prompts |

---

## 4. LM Studio Integration

### 4.1 Setup Instructions

1. **Download LM Studio** from [lmstudio.ai](https://lmstudio.ai)
2. **Load a model:**
   - Recommended: `Qwen2.5-Coder-7B-Instruct` (best for code/infra)
   - Alternative: `Llama-3.1-8B-Instruct` (good general reasoning)
   - Minimum: `Phi-3-mini-4k` (if low RAM)
3. **Start the local server:**
   - Open LM Studio → Developer Tab → Start Server
   - Default endpoint: `http://localhost:1234/v1`
   - API format: OpenAI-compatible

### 4.2 Python Client for LM Studio

```python
# app/llm/client.py

import httpx
import json
from typing import Optional

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"

class LMStudioClient:
    """Client for LM Studio's OpenAI-compatible API."""
    
    def __init__(self, base_url: str = LM_STUDIO_BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=120.0)
    
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False
    ) -> str:
        """Send a chat completion request to LM Studio."""
        payload = {
            "model": "local-model",  # LM Studio ignores this, uses loaded model
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    def generate_ir(self, user_requirement: str) -> dict:
        """Generate Universal IR from natural language requirement."""
        system_prompt = """You are an infrastructure planning AI.
Given a natural language requirement, output a valid JSON object
representing the Universal Infrastructure Plan (IR).

You MUST respond with ONLY valid JSON. No markdown. No explanation.

Required JSON structure:
{
  "intent": "create_database" | "deploy_cloud" | "create_database_and_deploy_cloud",
  "database": { ... } or null,
  "cloud": { ... } or null,
  "dependencies": [...],
  "assumptions": [...]
}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_requirement}
        ]
        
        raw_response = self.chat(messages, json_mode=True, temperature=0.1)
        
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            # Attempt to extract JSON from response
            start = raw_response.find('{')
            end = raw_response.rfind('}') + 1
            return json.loads(raw_response[start:end])
    
    def ask_clarification(self, user_requirement: str) -> str:
        """Generate clarifying questions if requirement is incomplete."""
        system_prompt = """You are an infrastructure planning assistant.
Analyze the user's requirement. If critical information is missing
(e.g., database type, region, instance size, relationships),
generate 2-4 concise clarifying questions.
If the requirement is complete, respond with exactly: "READY"
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_requirement}
        ]
        
        return self.chat(messages, temperature=0.3)


# Singleton instance
llm_client = LMStudioClient()
```

### 4.3 LM Studio Configuration for This Project

| Setting | Value | Why |
|---------|-------|-----|
| Temperature | `0.1 - 0.3` | Deterministic infrastructure plans |
| Max Tokens | `4096` | Large IR JSON outputs |
| Context Length | `8192+` | Long schemas + conversations |
| JSON Mode | **Enabled** | Force structured IR output |
| GPU Offload | Max available | Faster inference |
| Repeat Penalty | `1.05` | Prevent looping in generation |

---

## 5. Human-in-the-Loop Workflow

### 5.1 The Approval Pipeline

```text
┌────────────────────────────────────────────────────────────────────┐
│                 HUMAN-IN-THE-LOOP WORKFLOW                         │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  1. USER INPUT (Natural Language)                                  │
│     "I need a PostgreSQL database for student management"          │
│                          │                                         │
│                          ▼                                         │
│  2. LM STUDIO PLANS (AI generates Universal IR)                    │
│     → Structured JSON plan                                         │
│                          │                                         │
│                          ▼                                         │
│  3. VALIDATION ENGINE (Deterministic checks)                       │
│     → Syntax ✓ | Security ✓ | Dependencies ✓                       │
│                          │                                         │
│                          ▼                                         │
│  4. ⚠️ HUMAN APPROVAL GATE ⚠️                                      │
│     ┌──────────────────────────────────────────┐                   │
│     │  PLAN PREVIEW:                            │                   │
│     │  • CREATE TABLE students                  │                   │
│     │  • CREATE TABLE departments               │                   │
│     │  • AWS: VPC + RDS PostgreSQL              │                   │
│     │  • Est. Cost: ~$15/month                  │                   │
│     │                                           │                   │
│     │  Risk Level: 🟡 MEDIUM                    │                   │
│     │                                           │                   │
│     │  [✅ APPROVE]  [✏️ EDIT]  [❌ REJECT]     │                   │
│     └──────────────────────────────────────────┘                   │
│                          │                                         │
│              ┌───────────┼───────────┐                             │
│              ▼           ▼           ▼                             │
│           APPROVE      EDIT       REJECT                           │
│              │           │           │                             │
│              ▼           ▼           ▼                             │
│         EXECUTE     MODIFY &    CANCEL &                           │
│              │      RE-SUBMIT     LOG                              │
│              ▼                                                     │
│  5. EXECUTION ENGINE                                               │
│     → terraform apply (against LocalStack)                         │
│     → SQL execution (against local PostgreSQL)                     │
│                          │                                         │
│                          ▼                                         │
│  6. VERIFICATION & AUDIT                                           │
│     → Compare desired vs actual state                              │
│     → Log to immutable audit trail                                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 5.2 Approval Rules Matrix

| Operation Type | Risk | Auto-Execute? | Approval Required |
|---------------|------|---------------|-------------------|
| Read / Introspect schema | 🟢 Low | ✅ Yes | No |
| Generate plan (no execution) | 🟢 Low | ✅ Yes | No |
| CREATE TABLE | 🟡 Medium | ❌ No | Single click |
| CREATE cloud resource | 🟡 Medium | ❌ No | Single click |
| ALTER / MODIFY | 🟠 High | ❌ No | Confirmation text |
| DROP / DELETE | 🔴 Critical | ❌ No | Type "DELETE" to confirm |
| IAM / Security changes | 🔴 Critical | ❌ No | Type + MFA (future) |

### 5.3 Approval API Endpoints

```python
# FastAPI endpoints for human-in-the-loop

from fastapi import APIRouter, HTTPException
from enum import Enum

router = APIRouter()

class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"

@router.post("/plans/{plan_id}/approval")
async def submit_approval(
    plan_id: str,
    decision: ApprovalDecision,
    modifications: Optional[dict] = None,
    confirmation_text: Optional[str] = None
):
    """Human submits their approval decision."""
    
    plan = await get_plan(plan_id)
    
    # Check if high-risk requires confirmation text
    if plan.risk_level == "critical" and decision == ApprovalDecision.APPROVE:
        if confirmation_text != plan.confirmation_phrase:
            raise HTTPException(400, "Confirmation text required for critical ops")
    
    if decision == ApprovalDecision.APPROVE:
        # Queue for execution
        await execution_queue.enqueue(plan)
        return {"status": "queued_for_execution", "plan_id": plan_id}
    
    elif decision == ApprovalDecision.REJECT:
        await audit_log.record(plan_id, "REJECTED")
        return {"status": "rejected", "plan_id": plan_id}
    
    elif decision == ApprovalDecision.MODIFY:
        # Send back to LLM with modification instructions
        revised_plan = await llm_client.revise_plan(plan, modifications)
        return {"status": "revising", "new_plan_id": revised_plan.id}
```

---

## 6. Multi-Cloud Architecture

### 6.1 Design: AWS Now, Azure Later

The system is **designed for multi-cloud** but **implemented for AWS first**.

```text
┌─────────────────────────────────────────────────────────────┐
│              UNIVERSAL CLOUD IR (Provider-Agnostic)          │
│                                                             │
│  {                                                          │
│    "intent": "deploy_cloud",                                │
│    "resources": [                                           │
│      {"type": "virtual_network", "cidr": "10.0.0.0/16"},   │
│      {"type": "managed_database", "engine": "postgresql"}, │
│      {"type": "object_storage", "name": "app-assets"}      │
│    ]                                                        │
│  }                                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ AWS MAPPER │ │AZURE MAPPER│ │ GCP MAPPER │
     │ (ACTIVE)   │ │ (PLANNED)  │ │ (PLANNED)  │
     │            │ │            │ │            │
     │ vnet → VPC │ │ vnet → VNet│ │ vnet → VPC │
     │ rds → RDS  │ │ db → SQL DB│ │ db → SQL   │
     │ s3 → S3    │ │ store→Blob │ │ store→ GCS │
     └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
           │               │               │
           ▼               ▼               ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ Terraform  │ │ Terraform  │ │ Terraform  │
     │ AWS HCL    │ │ Azure HCL  │ │ GCP HCL    │
     │            │ │            │ │            │
     │ LocalStack │ │ (Future)   │ │ (Future)   │
     └────────────┘ └────────────┘ └────────────┘
```

### 6.2 Universal Resource Mapping Table

| Universal Concept | AWS Resource | Azure Resource | GCP Resource |
|-------------------|-------------|----------------|--------------|
| `virtual_network` | `aws_vpc` | `azurerm_virtual_network` | `google_compute_network` |
| `subnet` | `aws_subnet` | `azurerm_subnet` | `google_compute_subnetwork` |
| `managed_database` | `aws_db_instance` | `azurerm_postgresql_flexible_server` | `google_sql_database_instance` |
| `object_storage` | `aws_s3_bucket` | `azurerm_storage_blob` | `google_storage_bucket` |
| `compute_instance` | `aws_instance` | `azurerm_linux_virtual_machine` | `google_compute_instance` |
| `security_rule` | `aws_security_group` | `azurerm_network_security_group` | `google_compute_firewall` |
| `load_balancer` | `aws_lb` | `azurerm_lb` | `google_compute_global_forwarding_rule` |
| `dns_record` | `aws_route53_record` | `azurerm_dns_a_record` | `google_dns_record_set` |

### 6.3 Provider Adapter Interface

```python
# app/adapters/cloud/base.py

from abc import ABC, abstractmethod
from typing import List

class CloudProviderAdapter(ABC):
    """Abstract base for cloud providers."""
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider identifier: 'aws', 'azure', 'gcp'"""
        pass
    
    @abstractmethod
    def map_resources(self, universal_ir: dict) -> dict:
        """Map universal IR to provider-specific resource types."""
        pass
    
    @abstractmethod
    def generate_terraform(self, mapped_resources: dict) -> str:
        """Generate provider-specific Terraform HCL."""
        pass
    
    @abstractmethod
    def get_local_endpoint(self) -> str:
        """Return local simulation endpoint (LocalStack, Azurite, etc.)"""
        pass
    
    @abstractmethod
    def validate_plan(self, terraform_code: str) -> bool:
        """Run terraform validate."""
        pass


class AWSAdapter(CloudProviderAdapter):
    """AWS implementation — ACTIVE"""
    
    def get_provider_name(self) -> str:
        return "aws"
    
    def get_local_endpoint(self) -> str:
        return "http://localhost:4566"  # LocalStack
    
    def map_resources(self, universal_ir: dict) -> dict:
        mapping = {
            "virtual_network": "aws_vpc",
            "subnet": "aws_subnet",
            "managed_database": "aws_db_instance",
            "object_storage": "aws_s3_bucket",
            "compute_instance": "aws_instance",
            "security_rule": "aws_security_group",
        }
        # Apply mapping to IR
        pass
    
    def generate_terraform(self, mapped_resources: dict) -> str:
        # Generate AWS-specific HCL
        pass
    
    def validate_plan(self, terraform_code: str) -> bool:
        # Run terraform validate
        pass


class AzureAdapter(CloudProviderAdapter):
    """Azure implementation — PLANNED (Not yet built)"""
    
    def get_provider_name(self) -> str:
        return "azure"
    
    def get_local_endpoint(self) -> str:
        return "http://localhost:10000"  # Azurite (Azure Storage Emulator)
    
    def map_resources(self, universal_ir: dict) -> dict:
        raise NotImplementedError("Azure adapter not yet implemented")
    
    def generate_terraform(self, mapped_resources: dict) -> str:
        raise NotImplementedError("Azure adapter not yet implemented")
    
    def validate_plan(self, terraform_code: str) -> bool:
        raise NotImplementedError("Azure adapter not yet implemented")
```

---

## 7. LocalStack Setup & Configuration

### 7.1 Docker Compose (Full Stack)

```yaml
# docker-compose.yml

version: "3.9"

services:
  # ============================================
  # LOCALSTACK — AWS Simulation
  # ============================================
  localstack:
    image: localstack/localstack:latest
    container_name: vellum-localstack
    ports:
      - "4566:4566"            # Main AWS API endpoint
      - "4510-4559:4510-4559"  # External services range
    environment:
      - SERVICES=s3,ec2,vpc,rds,iam,sts,cloudwatch
      - DEBUG=1
      - DOCKER_HOST=unix:///var/run/docker.sock
      - AWS_ACCESS_KEY_ID=test
      - AWS_SECRET_ACCESS_KEY=test
      - AWS_DEFAULT_REGION=us-east-1
    volumes:
      - "./localstack-data:/var/lib/localstack"
      - "/var/run/docker.sock:/var/run/docker.sock"
      - "./scripts/localstack-init.sh:/etc/localstack/init/ready.d/init.sh"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ============================================
  # POSTGRESQL — Local database for testing
  # ============================================
  postgres:
    image: postgres:15-alpine
    container_name: vellum-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: vellum
      POSTGRES_PASSWORD: dev_password_only
      POSTGRES_DB: vellum_metadata
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vellum"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ============================================
  # REDIS — Task queue + cache
  # ============================================
  redis:
    image: redis:7-alpine
    container_name: vellum-redis
    ports:
      - "6379:6379"

  # ============================================
  # BACKEND API (FastAPI)
  # ============================================
  backend:
    build: ./backend
    container_name: vellum-backend
    ports:
      - "8000:8000"
    environment:
      - CLOUD_ENV=local
      - LOCALSTACK_URL=http://localstack:4566
      - DATABASE_URL=postgresql://vellum:dev_password_only@postgres:5432/vellum_metadata
      - REDIS_URL=redis://redis:6379/0
      - LM_STUDIO_URL=http://host.docker.internal:1234/v1
      - HUMAN_APPROVAL_REQUIRED=true
    depends_on:
      localstack:
        condition: service_healthy
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - ./backend:/app
      - ./terraform-workspace:/terraform-workspace

volumes:
  postgres-data:
```

### 7.2 LocalStack Init Script

```bash
#!/bin/bash
# scripts/localstack-init.sh
# Runs automatically when LocalStack is ready

echo "Initializing LocalStack resources for Vellum..."

# Create a test S3 bucket
awslocal s3 mb s3://vellum-artifacts

# Create a test VPC
awslocal ec2 create-vpc --cidr-block 10.0.0.0/16

echo "LocalStack initialization complete."
```

### 7.3 Environment Variables

```bash
# .env

# === CLOUD ENVIRONMENT ===
CLOUD_ENV=local
CLOUD_PROVIDER=aws

# === LOCALSTACK ===
LOCALSTACK_URL=http://localhost:4566
LOCALSTACK_REGION=us-east-1
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test

# === LM STUDIO ===
LM_STUDIO_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=local-model
LM_STUDIO_TEMPERATURE=0.2
LM_STUDIO_MAX_TOKENS=4096

# === DATABASE ===
DATABASE_URL=postgresql://vellum:dev_password_only@localhost:5432/vellum_metadata

# === REDIS ===
REDIS_URL=redis://localhost:6379/0

# === HUMAN IN THE LOOP ===
HUMAN_APPROVAL_REQUIRED=true
AUTO_EXECUTE_READ_ONLY=true

# === TERRAFORM ===
TERRAFORM_WORKSPACE=./terraform-workspace
TERRAFORM_BINARY=terraform
```

---

## 8. Module-Based Development Plan

### Overview

```text
Module 1: LM Studio Connection
    ↓ ✅ Verified
Module 2: Natural Language → Universal IR
    ↓ ✅ Verified
Module 3: Human-in-the-Loop Approval Gate
    ↓ ✅ Verified
Module 4: Terraform Generator (AWS)
    ↓ ✅ Verified
Module 5: LocalStack Execution Engine
    ↓ ✅ Verified
Module 6: Verification & Audit
    ↓ ✅ Verified
Module 7: End-to-End Pipeline
    ↓ ✅ Verified
Module 8: Frontend UI Integration
```

---

### Module 1: LM Studio Connection

**Goal:** Establish reliable communication with LM Studio.

**Tasks:**
- [ ] Install and start LM Studio with a model loaded
- [ ] Create `LMStudioClient` class
- [ ] Implement health check endpoint
- [ ] Test basic chat completion
- [ ] Test JSON mode response

**✅ Verification Checkpoint 1:**
```python
# test_module_1.py
from app.llm.client import llm_client

def test_lm_studio_connection():
    response = llm_client.chat([
        {"role": "user", "content": "Respond with exactly: HELLO_VELLUM"}
    ])
    assert "HELLO_VELLUM" in response

def test_lm_studio_json_mode():
    response = llm_client.chat([
        {"role": "user", "content": "Return JSON: {\"status\": \"ok\"}"}
    ], json_mode=True)
    import json
    data = json.loads(response)
    assert data["status"] == "ok"
```

---

### Module 2: Natural Language → Universal IR

**Goal:** Convert user requirements into structured infrastructure plans.

**Tasks:**
- [ ] Define Universal IR JSON schema (Pydantic models)
- [ ] Create system prompt for IR generation
- [ ] Implement clarification loop (detect missing info)
- [ ] Parse and validate LLM JSON output
- [ ] Handle malformed responses gracefully

**✅ Verification Checkpoint 2:**
```python
def test_nl_to_ir():
    user_input = """
    I need a student management database with PostgreSQL.
    Students have name, email. They belong to departments.
    Deploy to AWS with a private database.
    """
    
    ir = llm_client.generate_ir(user_input)
    
    # Validate structure
    assert ir["intent"] in ["create_database", "create_database_and_deploy_cloud"]
    assert ir["database"]["provider"] == "postgresql"
    assert len(ir["database"]["tables"]) >= 2
    assert ir["cloud"]["provider"] == "aws"
```

---

### Module 3: Human-in-the-Loop Approval Gate

**Goal:** Ensure NO execution happens without explicit human consent.

**Tasks:**
- [ ] Create plan preview formatter (human-readable)
- [ ] Implement approval state machine
- [ ] Add risk classification logic
- [ ] Build approval API endpoints
- [ ] Add rejection and modification flows

**✅ Verification Checkpoint 3:**
```python
def test_approval_gate_blocks_execution():
    plan = {"intent": "create_database_and_deploy_cloud", "database": {...}}
    engine = ApprovalEngine()
    
    assert engine.requires_approval(plan) == True
    
    risk = engine.classify_risk(plan)
    assert risk == RiskLevel.MEDIUM
    
    preview = engine.format_plan_preview(plan)
    assert "APPROVE" in preview
    assert "CREATE TABLE" in preview
```

---

### Module 4: Terraform Generator (AWS)

**Goal:** Convert Universal IR into valid AWS Terraform HCL.

**Tasks:**
- [ ] Create AWS resource mapper
- [ ] Implement HCL template engine
- [ ] Add LocalStack provider overrides
- [ ] Generate `variables.tf`, `main.tf`, `outputs.tf`
- [ ] Run `terraform fmt` and `terraform validate`

**Code (Excerpt showing Vellum tagging):**
```python
    def _hcl_vpc(self, name: str, props: dict) -> str:
        cidr = props.get("cidr_block", "10.0.0.0/16")
        return f'''
resource "aws_vpc" "{name}" {{
  cidr_block           = "{cidr}"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
'''
```

**✅ Verification Checkpoint 4:**
```python
def test_terraform_generation():
    ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "resources": [
                {"type": "virtual_network", "name": "test_vpc", "properties": {"cidr_block": "10.0.0.0/16"}},
                {"type": "object_storage", "name": "test-bucket", "properties": {}}
            ]
        }
    }
    
    generator = TerraformGenerator()
    plan_dir = generator.generate(ir, environment="local")
    
    # Check file exists
    assert (Path(plan_dir) / "main.tf").exists()
    
    # Check LocalStack endpoint is in the file
    content = (Path(plan_dir) / "main.tf").read_text()
    assert "localhost:4566" in content
    assert "aws_vpc" in content
    assert "aws_s3_bucket" in content
    assert "Vellum" in content
```

---

### Module 5: LocalStack Execution Engine

**Goal:** Execute approved Terraform plans against LocalStack.

**Tasks:**
- [ ] Implement `terraform init` → `plan` → `apply` workflow
- [ ] Capture and parse execution output
- [ ] Handle errors and timeouts
- [ ] Log execution to audit trail
- [ ] Support rollback (terraform destroy)

**✅ Verification Checkpoint 5:**
```python
def test_execution_against_localstack():
    # Generate a plan first (from Module 4)
    generator = TerraformGenerator()
    plan_dir = generator.generate(test_ir, environment="local")
    
    # Execute it
    engine = ExecutionEngine()
    result = engine.execute_plan(plan_dir, plan_id="test_001")
    
    assert result.success == True
    assert result.resources_created > 0
    
    # Verify in LocalStack
    import boto3
    s3 = boto3.client('s3', endpoint_url='http://localhost:4566')
    buckets = s3.list_buckets()['Buckets']
    assert any('test' in b['Name'] for b in buckets)
```

---

### Module 6: Verification & Audit

**Goal:** Confirm execution succeeded and log everything.

**Tasks:**
- [ ] Query LocalStack for actual state
- [ ] Compare actual vs desired (Universal IR)
- [ ] Generate verification report
- [ ] Write to immutable audit log
- [ ] Detect drift

**✅ Verification Checkpoint 6:**
```python
def test_verification():
    verifier = VerificationEngine()
    report = verifier.verify(plan_id="test_001", expected_ir=test_ir)
    
    assert report["status"] == "success"
    assert report["drift_detected"] == False
    assert report["resources_verified"] > 0
```

---

### Module 7: End-to-End Pipeline

**Goal:** Connect all modules into a single working flow.

**Tasks:**
- [ ] Wire LM Studio → IR → Approval → Terraform → Execute → Verify
- [ ] Add WebSocket for real-time progress updates
- [ ] Handle errors at each stage gracefully
- [ ] Full integration test

**✅ Verification Checkpoint 7:**
```python
def test_full_pipeline():
    # 1. Natural Language Input
    user_input = "Create an S3 bucket called vellum-app-assets on AWS"
    
    # 2. LM Studio generates IR
    ir = llm_client.generate_ir(user_input)
    
    # 3. Check approval needed
    assert approval_engine.requires_approval(ir) == True
    
    # 4. Simulate human approval
    plan_id = "e2e_test_001"
    
    # 5. Generate Terraform
    plan_dir = tf_generator.generate(ir, environment="local")
    
    # 6. Execute
    result = execution_engine.execute_plan(plan_dir, plan_id)
    assert result.success == True
    
    # 7. Verify
    report = verifier.verify(plan_id, ir)
    assert report["status"] == "success"
    
    # 8. Check audit log
    audit = audit_engine.get_log(plan_id)
    assert audit is not None
```

---

### Module 8: Frontend UI Integration

**Goal:** Build the React UI for chat, plan review, and approval.

**Tasks:**
- [ ] Chat interface (send NL, receive clarifying questions)
- [ ] Plan preview panel (formatted IR display)
- [ ] Approval buttons (Approve / Modify / Reject)
- [ ] Real-time execution progress (WebSocket)
- [ ] Audit log viewer

**✅ Verification Checkpoint 8:**
- [ ] Open browser → type requirement → see plan → click Approve → see execution progress → see success

---

## 9. Verification Checkpoints Summary

| Module | Checkpoint | Pass Criteria |
|--------|-----------|---------------|
| 1 | LM Studio responds | Chat + JSON mode work |
| 2 | NL → IR | Valid structured JSON from natural language |
| 3 | Approval gate blocks | No execution without approval |
| 4 | Terraform generated | Valid HCL with LocalStack endpoints |
| 5 | LocalStack execution | Resources created in LocalStack |
| 6 | Verification passes | Actual state matches desired |
| 7 | Full pipeline | NL → Deploy → Verify in one flow |
| 8 | UI works | Human can interact via browser |

---

## 10. Code Templates

### Quick Start Script

```bash
#!/bin/bash
# setup.sh — Run this once to set up the project

echo "🚀 Setting up Vellum with LocalStack..."

# 1. Start infrastructure
docker-compose up -d

# 2. Wait for LocalStack
echo "⏳ Waiting for LocalStack..."
until curl -s http://localhost:4566/_localstack/health | grep -q "running"; do
    sleep 2
done
echo "✅ LocalStack is ready"

# 3. Install Python dependencies
cd backend
pip install -r requirements.txt
cd ..

# 4. Install frontend dependencies
cd frontend
npm install
cd ..

# 5. Check LM Studio
echo "🔍 Checking LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo "✅ LM Studio is running"
else
    echo "❌ LM Studio not detected. Please start it manually."
    echo "   → Open LM Studio → Developer → Start Server"
fi

echo ""
echo "✅ Setup complete!"
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:3000"
echo "   LocalStack: http://localhost:4566"
echo "   LM Studio: http://localhost:1234"
```

### Requirements.txt

```text
# backend/requirements.txt

# Web
fastapi==0.104.0
uvicorn[standard]==0.24.0
websockets==12.0

# Database
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.12.0

# AI / LLM
httpx==0.25.0
openai==1.3.0  # For LM Studio OpenAI-compatible API

# Cloud / AWS
boto3==1.34.0
botocore==1.34.0

# Task Queue
celery==5.3.0
redis==5.0.0

# Validation
pydantic==2.5.0
pydantic-settings==2.1.0

# Utilities
python-dotenv==1.0.0
jinja2==3.1.2
structlog==23.2.0

# Testing
pytest==7.4.0
pytest-asyncio==0.23.0
moto==4.2.0  # For unit tests without LocalStack
```

---

## 11. Rules for AI Assistant

When working on this project, the AI assistant MUST follow these rules:

### Architecture Rules

1. **Never bypass the approval gate.** All destructive operations require human confirmation.
2. **Never expose credentials to the LLM.** All secrets stay in the Credential Manager.
3. **Always generate Universal IR first.** Never generate Terraform directly from NL.
4. **Always validate before execution.** Run `terraform validate` before `apply`.
5. **Always use LocalStack in development.** Never hit real AWS APIs during testing.

### Code Rules

1. **Type hints required.** All Python functions must have type annotations.
2. **Pydantic for all schemas.** Never use raw dicts for IR validation.
3. **Error handling everywhere.** Every external call must have try/except.
4. **Logging at every step.** Use `structlog` for structured logging.
5. **Tests for every module.** Each module must have corresponding test file.

### LLM Prompt Rules

1. **Always use JSON mode** when expecting structured output.
2. **Temperature ≤ 0.3** for infrastructure planning.
3. **Include schema in system prompt** so LLM knows the expected output format.
4. **Validate LLM output** with Pydantic before using it.
5. **Retry on malformed JSON** (max 2 retries with error feedback).

### Security Rules

1. **No hardcoded secrets.** Use environment variables only.
2. **No `0.0.0.0/0` ingress** in generated security groups (unless explicitly requested).
3. **Encryption enabled by default** for all storage resources.
4. **Deletion protection** enabled for databases by default.
5. **All operations logged** to immutable audit trail.

---

## Appendix: Project Directory Structure

```text
vellum/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Environment configuration
│   │   ├── llm/
│   │   │   ├── client.py             # LM Studio client
│   │   │   ├── prompts.py            # System prompts
│   │   │   └── parser.py             # Response parsing
│   │   ├── schemas/
│   │   │   ├── ir.py                 # Universal IR models
│   │   │   ├── database.py           # DB schemas
│   │   │   └── cloud.py              # Cloud schemas
│   │   ├── engines/
│   │   │   ├── orchestrator.py       # AI orchestration
│   │   │   ├── terraform_generator.py # TF code generation
│   │   │   ├── execution_engine.py   # TF apply/destroy
│   │   │   └── verification_engine.py # State checking
│   │   ├── approval/
│   │   │   ├── engine.py             # Approval logic
│   │   │   └── models.py             # Approval states
│   │   ├── adapters/
│   │   │   ├── cloud/
│   │   │   │   ├── base.py           # Abstract cloud adapter
│   │   │   │   ├── aws.py            # AWS (ACTIVE)
│   │   │   │   └── azure.py          # Azure (PLANNED)
│   │   │   └── database/
│   │   │       ├── base.py           # Abstract DB adapter
│   │   │       ├── postgresql.py     # PostgreSQL
│   │   │       └── mysql.py          # MySQL (PLANNED)
│   │   ├── validation/
│   │   │   ├── syntax.py             # Syntax validation
│   │   │   ├── security.py           # Security rules
│   │   │   └── policy.py             # Policy engine
│   │   ├── credentials/
│   │   │   └── manager.py            # Credential isolation
│   │   └── audit/
│   │       └── logger.py             # Immutable audit log
│   ├── tests/
│   │   ├── test_module_1_lm_studio.py
│   │   ├── test_module_2_ir_generation.py
│   │   ├── test_module_3_approval.py
│   │   ├── test_module_4_terraform.py
│   │   ├── test_module_5_execution.py
│   │   ├── test_module_6_verification.py
│   │   └── test_module_7_e2e.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/                 # AI chat interface
│   │   │   ├── PlanPreview/          # Plan display + approval
│   │   │   ├── ExecutionProgress/    # Real-time progress
│   │   │   └── AuditLog/            # History viewer
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── Dockerfile
├── terraform-workspace/              # Generated TF files go here
├── localstack-data/                  # LocalStack persistent data
├── scripts/
│   ├── setup.sh                      # Initial setup
│   └── localstack-init.sh           # LocalStack bootstrap
├── docker-compose.yml
├── .env
├── README.md
└── docs/
    └── AI_AGENT_WORKFLOW.md          # This file
```

---

*Document Version: 1.1*
*Project: Vellum — AI-Driven NLP Autonomous Infrastructure Designer*
*Generated: October 04, 2026*
```
