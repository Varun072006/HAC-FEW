# Zeroth Review: Hierarchical Agent Coordination Framework for Complex Enterprise Workflows
**Mini Project Review Document (Updated Planning Basis)**

---

## 1. Project Title & Overview
- **Title**: Hierarchical Agent Coordination Framework for Complex Enterprise Workflows
- **Objective**: Design and build an observable, governed multi-agent orchestration architecture where a centralized **Supervisor Agent** plans, decomposes, schedules, and supervises domain-specialized sub-agents (**HR**, **Finance**, **IT**) executing cross-system workflows with deterministic schema contracts, policy-grounded RAG, and typed tool executions.
- **Core Research Question**: *Does hierarchical multi-agent coordination outperform an unconstrained single-agent baseline on multi-department enterprise tasks in task success rate, accuracy, groundedness, and action safety?*

---

## 2. System Architecture & High-Level Components
1. **API Gateway**: Entry point handling JWT authentication, Role-Based Access Control (RBAC), and request rate limiting.
2. **Supervisor Agent (LangGraph)**:
   - Intent classification and decomposition into a directed acyclic task graph (DAG).
   - Execution scheduler running independent tasks in parallel and dependent tasks in order.
   - Pydantic schema validation for all sub-agent input/output contracts.
   - Dynamic replanner triggered on tool timeouts, policy violations, or sub-agent errors.
   - Synthesizer compiling cited final responses.
3. **Specialized Agents**:
   - **HR Agent**: Manages employee lifecycle records, onboarding status, and leave policies.
   - **Finance Agent**: Computes expense approvals, reimbursement thresholds, and payroll setup.
   - **IT Agent**: Triage incidents, classifies severity levels, provisions accounts/hardware tickets.
4. **Governed Tool Layer**:
   - Strict separation of read-only tools vs. state-mutating write tools.
   - Explicit agent allow-listing (least privilege).
5. **Mock Enterprise Microservices**:
   - Synthetic REST services mimicking HRMS, ERP (Finance), and IT Ticketing backends.

---

## 3. Technology Stack & Feasibility
- **Orchestration**: LangGraph (state machine, checkpointing, human interrupts).
- **Inference Engine**: Ollama (Llama 3.1 8B local) with hosted fallback (OpenAI/Anthropic).
- **Backend & Schemas**: FastAPI, Pydantic v2, SQLAlchemy, Uvicorn.
- **Persistence & Vector Store**: PostgreSQL with `pgvector`.
- **Embeddings**: BAAI `bge-small-en-v1.5` / `nomic-embed-text`.
- **Observability**: Langfuse / OpenTelemetry execution trace tracking.
- **Deployment**: Docker Compose.

---

## 4. Governance & Safety Module (New Specification)
To eliminate risks inherent to unconstrained enterprise autonomous agents, the governance module enforces:
1. **Three-Tier Risk Classification**:
   - **Tier 1 (Low Risk - Read-Only)**: Automatically executed without delay.
   - **Tier 2 (Medium Risk - Reversible Writes)**: Executed automatically with immutable audit logging and rollback capabilities.
   - **Tier 3 (High Risk - Financial, Access, Deletion, External Send)**: Execution paused via LangGraph interrupt; routes to an explicit Human-in-the-Loop (HITL) approval gate.
2. **Deterministic Policy Engine**:
   - Intercepts every write action prior to tool execution.
   - Evaluates parameters against enterprise policy rules (e.g., maximum expense thresholds, dual sign-offs).
3. **Prompt Injection & Data Boundary Defense**:
   - Strict separation between retrieved document text and executable instructions.
   - Input sanitization layer rejecting jailbreak attempts and instruction overrides.
4. **Immutable Audit Log**:
   - Every state transition, agent decision rationale, tool parameter payload, and approval signature is captured into PostgreSQL.

---

## 5. Evaluation Methodology & Metrics (New Specification)
The project evaluates the framework against a **Single-Agent Baseline** across a 50+ scenario synthetic benchmark.

| Metric | Target | Definition |
| :--- | :--- | :--- |
| **Task Success Rate** | $\ge 85\%$ (above baseline) | Percentage of workflows completing with correct business outcome |
| **Routing Accuracy** | $\ge 90\%$ | Correct sub-agent assigned per decomposed sub-task |
| **Plan Quality** | $\ge 80\%$ | Decomposed DAG matching expected sub-task order and dependencies |
| **RAG Recall@5** | $\ge 0.80$ | Top-5 retrieved chunks contain the ground-truth policy rule |
| **Groundedness / Faithfulness** | $\ge 90\%$ | Output claims supported by cited policy chunk IDs |
| **Safety Violation Rate** | $0$ violations | Zero unauthorized writes or prompt injection bypasses |
| **P95 Latency** | $< 15\text{s}$ | End-to-end execution latency for simple workflows on local 8B model |

### Experimental Ablation Matrix
1. **Hierarchical Multi-Agent vs. Single-Agent Baseline**: Evaluate identical requests to measure plan hallucination and coordination stability.
2. **Ablation 1 (No RAG)**: Measure policy compliance and hallucination rate without document retrieval grounding.
3. **Ablation 2 (No Replanner)**: Measure recovery rate when tools return synthetic errors or timeouts.
4. **Ablation 3 (No Policy Gate)**: Measure safety breach frequency under red-team adversarial prompts.
5. **Model Scale Comparison**: Local Llama 3.1 8B vs. Hosted Frontier LLM.

---

## 6. Assumptions & Limitations (New Specification)
1. **Synthetic Data**: All employee profiles, tickets, financial figures, and policies are synthetically generated; no live corporate or PII data is utilized.
2. **Local Model Constraints**: Llama 3.1 8B may occasionally exhibit schema generation variance; mitigated via Pydantic constrained decoding and automatic retry loops.
3. **Mock Integrations**: Mock services run as lightweight REST containers rather than complex proprietary SAP/Workday instances.
4. **Held-Out Evaluation Split**: 20% of benchmark scenarios are held out from prompt tuning to prevent benchmark overfitting.
