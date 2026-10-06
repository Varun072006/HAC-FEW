"""
Streamlit Web UI: Hierarchical Agent Coordination Framework
Visualizes:
- Natural Language Enterprise Workflow Dispatcher
- Dynamic Task Graph & Dependency Tracing
- Real-Time Sub-Agent Execution Output & Latency
- RAG Policy Retrieval Citations
- Human-in-the-Loop (HITL) Approvals Gate
- Immutable Audit Logs
"""
import streamlit as st
import json
import uuid
import time
from datetime import datetime

from core.supervisor.orchestrator import SupervisorOrchestrator
from core.rag.retriever import HybridPolicyRetriever
from mock_systems.db import SessionLocal
from mock_systems.models import AuditLog, Employee, ExpenseRecord, ITTicket

st.set_page_config(
    page_title="Hierarchical Agent Coordination Framework",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header { font-size: 26px; font-weight: 700; color: #1E293B; margin-bottom: 4px; }
    .sub-header { font-size: 14px; color: #64748B; margin-bottom: 20px; }
    .badge-low { background-color: #DCFCE7; color: #166534; padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    .badge-med { background-color: #FEF3C7; color: #92400E; padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    .badge-high { background-color: #FEE2E2; color: #991B1B; padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    .card { background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)

# Initialize Orchestrator in session state
if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = SupervisorOrchestrator()
    st.session_state.history = []

orchestrator = st.session_state.orchestrator

# Sidebar: Configuration & Presets
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/network.png", width=64)
    st.title("Framework Control")
    
    st.subheader("User Identity & Role")
    user_role = st.selectbox("Active Role", ["employee", "manager", "director", "hr_rep", "it_admin", "admin"], index=1)
    user_id = st.text_input("User ID", value="EMP-001")

    st.divider()
    st.subheader("Flagship Workflow Presets")
    preset = st.radio(
        "Choose test scenario:",
        [
            "Custom Query",
            "1. Onboard Elena Rostova (HR + IT + Fin)",
            "2a. Low Expense ($45 Coffee - Auto Approve)",
            "2b. Mod Expense ($350 Dinner - Line Manager)",
            "2c. High Expense ($2,400 Conf - Dual Approval)",
            "2d. Missing Receipt ($85 Taxi - Rejection)",
            "3a. Critical IT Outage (Sev-1 DB Outage)"
        ]
    )

st.markdown('<div class="main-header">Hierarchical Agent Coordination Framework</div>', unsafe_allow_html=True)
tabs = st.tabs([
    "🚀 Workflow Execution",
    "🗺️ Agent Graph Architecture",
    "🛡️ Governance & Approval Gate",
    "📚 RAG Knowledge Base",
    "📜 Audit Log & System State"
])

# --- TAB 1: WORKFLOW EXECUTION ---
with tabs[0]:
    # Determine prompt text from preset
    default_text = ""
    if "Onboard Elena" in preset:
        default_text = f"Please onboard Elena Rostova (elena.{uuid.uuid4().hex[:4]}@company.test) as Staff Frontend Engineer in Engineering. Set up payroll and assign laptop."
    elif "Low Expense" in preset:
        default_text = "Submit expense reimbursement for EMP-001: $45.00 for client coffee with receipt attached."
    elif "Mod Expense" in preset:
        default_text = "Submit expense reimbursement for EMP-001: $350.00 for client dinner in Chicago with itemized receipt attached."
    elif "High Expense" in preset:
        default_text = "Submit expense reimbursement for EMP-001: $2,400.00 for annual engineering tech conference. Receipt attached."
    elif "Missing Receipt" in preset:
        default_text = "Submit expense reimbursement for EMP-001: $85.00 for airport taxi without receipt."
    elif "Critical IT" in preset:
        default_text = "Critical alert: Total production database outage across all zones. Customers experiencing 500 errors."

    user_prompt = st.text_area("Enterprise Request Prompt", value=default_text, height=90, placeholder="Enter enterprise workflow request...")
    
    col_btn, col_metric1, col_metric2 = st.columns([1, 1, 1])
    with col_btn:
        run_clicked = st.button("⚡ Dispatch Workflow", type="primary", use_container_width=True)

    if run_clicked and user_prompt.strip():
        with st.spinner("Supervisor decomposing request & orchestrating specialized agents..."):
            # 1. Plan
            plan = orchestrator.plan_workflow(user_prompt)
            # 2. Execute
            synth = orchestrator.execute_workflow(plan, user_role=user_role)
            st.session_state.history.insert(0, {"plan": plan, "synth": synth, "timestamp": datetime.now().strftime("%H:%M:%S")})

    # Render Latest or Selected Workflow
    if st.session_state.history:
        latest = st.session_state.history[0]
        synth = latest["synth"]
        plan = latest["plan"]

        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Workflow Status", synth.status.upper())
        m2.metric("Sub-Tasks", len(synth.subtask_results))
        m3.metric("Latency", f"{synth.wall_clock_seconds} s")
        m4.metric("Citations Found", len(synth.citations))

        if synth.status == "awaiting_human_approval":
            st.warning("⚠️ **Human Approval Gate Intercepted**: This workflow contains high-risk operations requiring managerial authorization before state mutation.")
        elif synth.status == "success":
            st.success("✅ **Workflow Completed Successfully**: All sub-tasks verified and executed under governance rules.")
        else:
            st.error("❌ **Workflow Completed with Violations/Errors**: See subtask details below.")

        st.subheader("Execution DAG & Subtask Traces")
        for sub in synth.subtask_results:
            with st.expander(f"Task: `{sub.task_id}` | Agent: **{sub.agent.value.upper()}** | Status: `{sub.status.value}`", expanded=True):
                c_left, c_right = st.columns([2, 1])
                with c_left:
                    st.write("**Output Payload:**")
                    st.json(sub.output)
                    if sub.error_message:
                        st.error(f"Error / Rejection Reason: {sub.error_message}")
                with c_right:
                    st.write("**Tools Executed:**")
                    for t in sub.tool_calls_made:
                        st.code(t, language="bash")
                    if sub.citations:
                        st.write("**Policy Citations:**")
                        for cit in sub.citations:
                            st.info(cit)

# --- TAB 2: AGENT GRAPH ARCHITECTURE ---
with tabs[1]:
    st.subheader("🗺️ Hierarchical Multi-Agent Graph Architecture")
    st.write("Directed execution graph showing decomposition, delegation, policy interception, and tool mutation across the 4 architectural tiers.")
    
    mermaid_code = """
graph TD
    User(["👤 Enterprise User"]):::client
    Gateway["🛡️ API Gateway (Auth & RBAC)"]:::client
    User --> Gateway
    Gateway --> Supervisor["🧠 Supervisor Agent (LangGraph Planner)"]:::sup

    subgraph CoreEngine ["Central Coordination (Supervisor Engine)"]
        Supervisor --> Planner["📐 Task Graph Planner (JSON DAG)"]:::sup
        Planner --> Scheduler["⚡ Execution Scheduler"]:::sup
        Scheduler -.->|Tool Error| Replanner["🔄 Dynamic Replanner"]:::sup
        Replanner -.-> Scheduler
        Scheduler --> Synth["📝 Response Synthesizer"]:::sup
    end

    subgraph Agents ["Tier 2: Specialized Department Agents"]
        HRAgent["👔 HR Agent"]:::agt
        FinAgent["💰 Finance Agent"]:::agt
        ITAgent["💻 IT Agent"]:::agt
    end

    Scheduler -->|task_hr| HRAgent
    Scheduler -->|task_fin| FinAgent
    Scheduler -->|task_it| ITAgent

    subgraph SharedIntel ["Shared RAG & Knowledge Graph"]
        Retriever["🔍 Hybrid Retriever (Dense + Keyword)"]:::store
        GraphKB["🕸️ Enterprise GraphDB (Policies & Rules)"]:::store
    end

    HRAgent <--> Retriever
    FinAgent <--> Retriever
    ITAgent <--> Retriever
    FinAgent <--> GraphKB

    subgraph Gov ["Tier 3: Governance & Safety"]
        PolicyEngine{"⚖️ Policy Engine (3-Tier Risk)"}:::gov
        ApprovalGate["🛑 Human Approval Gate (HITL)"]:::gov
        AuditStore[("📜 Audit Log Store")]:::gov
    end

    HRAgent --> PolicyEngine
    FinAgent --> PolicyEngine
    ITAgent --> PolicyEngine

    PolicyEngine -->|Low/Med Risk| Tools["Tier 4: Typed Tools (Mock Systems)"]:::tool
    PolicyEngine -->|High Risk| ApprovalGate
    ApprovalGate -->|Authorized| Tools
    PolicyEngine --> AuditStore

    HRAgent -.-> Synth
    FinAgent -.-> Synth
    ITAgent -.-> Synth
    Synth --> User

    classDef client fill:#F1F5F9,stroke:#64748B,stroke-width:2px;
    classDef sup fill:#EFF6FF,stroke:#2563EB,stroke-width:2px;
    classDef agt fill:#FAF5FF,stroke:#9333EA,stroke-width:2px;
    classDef gov fill:#FEF2F2,stroke:#DC2626,stroke-width:2px;
    classDef store fill:#FFFBEB,stroke:#D97706,stroke-width:2px;
    classDef tool fill:#ECFDF5,stroke:#059669,stroke-width:2px;
"""
    st.markdown(f"```mermaid\n{mermaid_code}\n```")
    
    st.markdown("""
    ### Architectural Tiers Breakdown
    1. **Tier 1 - Supervisor Orchestrator**: LangGraph state machine handling intent classification, Pydantic DAG decomposition, and response synthesis.
    2. **Tier 2 - Specialized Department Agents**: Independent HR, Finance, and IT agents communicating exclusively via Pydantic JSON contracts.
    3. **Tier 3 - Governance & Safety Engine**: Deterministic policy rules, 3-tier risk gating (Low/Med/High), and human approval interrupt state.
    4. **Tier 4 - Typed Tool Layer & Knowledge Graph**: Allow-listed tools executing on mock systems + GraphDB/RAG knowledge store.
    """)

# --- TAB 3: GOVERNANCE & APPROVAL GATE ---
with tabs[2]:
    st.subheader("Human-in-the-Loop (HITL) Gate")
    st.write("Requests requiring human authorization under the 3-Tier Governance Matrix (e.g. expenses > $100, access elevation).")
    
    # Check database for items awaiting approval
    db = SessionLocal()
    pending_expenses = db.query(ExpenseRecord).filter(ExpenseRecord.status == "awaiting_approval").all()
    
    if not pending_expenses:
        st.info("No items currently pending approval.")
    else:
        for exp in pending_expenses:
            st.markdown(f"""
            <div class="card">
                <h4>Expense Claim: <code>{exp.id}</code> (Employee: {exp.employee_id})</h4>
                <p><b>Amount:</b> ${exp.amount:.2f} {exp.currency} | <b>Category:</b> {exp.category}</p>
                <p><b>Description:</b> {exp.description}</p>
            </div>
            """, unsafe_allow_html=True)
            col_a, col_r, _ = st.columns([1, 1, 3])
            with col_a:
                if st.button(f"✅ Authorize {exp.id}", key=f"app_{exp.id}"):
                    exp.status = "approved"
                    exp.approved_by = f"Human Approver ({user_role})"
                    db.commit()
                    st.success(f"{exp.id} Approved!")
                    st.rerun()
            with col_r:
                if st.button(f"❌ Deny {exp.id}", key=f"rej_{exp.id}"):
                    exp.status = "rejected"
                    db.commit()
                    st.warning(f"{exp.id} Denied!")
                    st.rerun()
    db.close()

# --- TAB 4: RAG KNOWLEDGE BASE ---
with tabs[3]:
    st.subheader("Enterprise Policies Corpus (RAG)")
    retriever = orchestrator.retriever
    
    col_q, col_role = st.columns([3, 1])
    with col_q:
        rag_search_query = st.text_input("Test Knowledge Base Search", value="expense approval limit receipts")
    with col_role:
        rag_test_role = st.selectbox("Test As Role", ["employee", "manager", "hr_rep", "it_admin", "guest_role"], index=0)
    
    if rag_search_query:
        rag_out = retriever.retrieve(rag_search_query, user_role=rag_test_role)
        if rag_out.abstain:
            st.warning(f"⚠️ Abstention Triggered: {rag_out.escalation_reason}")
        else:
            st.write(f"**Top Relevance Score:** `{rag_out.top_score:.3f}` | **Citations:** {rag_out.citations}")
            for r in rag_out.results:
                with st.expander(f"{r.citation} (Score: {r.score:.3f})"):
                    st.write(f"**Document ID:** `{r.doc_id}` | **Department:** `{r.department}`")
                    st.markdown(r.content)

# --- TAB 5: AUDIT LOG & SYSTEM STATE ---
with tabs[4]:
    st.subheader("Immutable Audit Log (PostgreSQL / SQLite)")
    db = SessionLocal()
    recent_logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(20).all()
    
    log_data = []
    for l in recent_logs:
        log_data.append({
            "ID": l.id,
            "Timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else "-",
            "Actor Agent": l.actor_agent,
            "Action": l.action,
            "Target": l.target_system,
            "Risk Tier": l.risk_level,
            "Status": l.status,
            "Reason": l.reason or ""
        })
    db.close()
    
    if log_data:
        st.dataframe(log_data, use_container_width=True)
    else:
        st.info("No audit entries logged yet.")
