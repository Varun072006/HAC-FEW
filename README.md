# Hierarchical Agent Coordination Framework for Complex Enterprise Workflows
> **S-5 Mini Project** | Assumed Duration: 12 Weeks

A governed, observable multi-agent system where a central **Supervisor Agent** plans, decomposes, and coordinates domain-specialized enterprise agents (**HR**, **Finance**, **IT**) executing complex workflows with deterministic schema contracts, policy-grounded RAG, typed tool execution, and human-in-the-loop approvals.

---

## 🏗 System Architecture

```mermaid
graph TD
    User([Enterprise User / Web UI]) --> Gateway[API Gateway (FastAPI, Auth, RBAC)]
    Gateway --> Sup[Supervisor Agent (LangGraph Planner)]
    
    subgraph Core Coordination
        Sup --> Scheduler[Execution Scheduler]
        Scheduler --> PEngine[Governance Policy Engine]
        PEngine -->|Risk Check & Approvals| ExecutionGate{Approval Gate}
    end
    
    ExecutionGate -->|Dispatched Subtasks| HRAgent[HR Agent]
    ExecutionGate -->|Dispatched Subtasks| FinAgent[Finance Agent]
    ExecutionGate -->|Dispatched Subtasks| ITAgent[IT Agent]
    
    subgraph Shared Services
        RAG[RAG Engine (pgvector + bge-small)]
        Audit[Immutable Audit Log (PostgreSQL)]
        Traces[Observability (Langfuse)]
    end
    
    HRAgent --> RAG
    FinAgent --> RAG
    ITAgent --> RAG
    
    HRAgent --> Tools[Typed Tool Layer]
    FinAgent --> Tools
    ITAgent --> Tools
    
    Tools --> MockSystems[Mock Enterprise Systems (HRMS, ERP, Ticketing)]
```

---

## 📁 Repository Structure

```
.
├── apps/
│   ├── api/             # FastAPI Gateway (Auth, RBAC, Routing)
│   └── web/             # Next.js / Streamlit Trace UI
├── core/
│   ├── supervisor/      # Planner, Scheduler, Replanner, Synthesizer, Schemas
│   ├── agents/          # HR, Finance, IT department agents
│   ├── tools/           # Typed tool wrappers for mock systems
│   ├── rag/             # Document ingestion, chunking, retrieval
│   └── governance/      # Policy Engine, RBAC, Approval Gate, Audit Logging
├── mock_systems/        # Simulated HRMS, ERP, and Ticketing REST APIs
├── data/
│   └── policies/        # Synthetic enterprise policy documents (HR, Finance, IT)
├── eval/                # Benchmark scenarios, Single-Agent baseline, metrics harness
├── deploy/              # Dockerfiles, CI/CD GitHub Actions workflows
├── docs/                # Architecture docs, Zeroth Review, Workflow specs
├── docker-compose.yml   # Multi-container orchestration (Postgres+pgvector, API, Mocks)
└── requirements.txt     # Python dependencies
```

---

## ⚡ Quickstart

### 1. Prerequisites
- Python 3.10+
- Docker & Docker Compose
- Ollama with `llama3.1:8b` (or `llama3:latest` / `qwen2.5:7b`)

### 2. Verify Local LLM
```bash
python core/verify_ollama_tools.py
```

### 3. Start Mock Systems & Database
```bash
docker compose up -d postgres mock-systems
```

### 4. Run the API Gateway
```bash
pip install -r requirements.txt
uvicorn apps.api.main:app --reload --port 8000
```

---

## 📊 Flagship Workflows
1. **Employee Onboarding**: HR creates employee profile, IT provisions accounts/hardware tickets, Finance initializes compensation & expense tiers.
2. **Expense Approval**: Finance Agent retrieves policies via RAG, checks financial thresholds, auto-approves low amounts (<$100) and triggers human approval gates for higher tiers.
3. **IT Incident Triage**: IT Agent classifies issue severity (Sev-1 to Sev-3), checks policies, creates tickets, and issues automated stakeholder escalation notices.

For full specifications and test cases, see [`docs/WORKFLOW_SPECS.md`](file:///docs/WORKFLOW_SPECS.md).
For project review basis and evaluation plan, see [`docs/ZEROTH_REVIEW.md`](file:///docs/ZEROTH_REVIEW.md).
# HAC-FEW
