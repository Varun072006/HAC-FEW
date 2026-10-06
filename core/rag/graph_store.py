"""
Enterprise Knowledge Graph (GraphRAG) Store.
Built on NetworkX to enable deterministic multi-hop reasoning over enterprise policies,
approval hierarchies, department domains, and risk-governed rules.
"""
import networkx as nx
from typing import Dict, Any, List, Optional, Tuple
import matplotlib.pyplot as plt
import io
import base64


class EnterpriseKnowledgeGraph:
    """
    In-memory directed knowledge graph modeling:
    - Policies, Sections, Rules, Actions, Roles, and Departments.
    """

    def __init__(self):
        self.graph = nx.DiGraph()
        self._build_enterprise_graph()

    def _build_enterprise_graph(self):
        self.graph.clear()

        # 1. Policies & Departments
        self.graph.add_node("POL-HR-001", type="Policy", label="HR Onboarding & Leave Policy", dept="HR")
        self.graph.add_node("POL-FIN-002", type="Policy", label="Travel & Expense Policy", dept="Finance")
        self.graph.add_node("POL-IT-003", type="Policy", label="IT Incident & Security Policy", dept="IT")

        self.graph.add_node("DEPT-ENG", type="Department", label="Engineering")
        self.graph.add_node("DEPT-FIN", type="Department", label="Finance")
        self.graph.add_node("DEPT-HR", type="Department", label="Human Resources")
        self.graph.add_node("DEPT-IT", type="Department", label="Information Technology")

        # 2. Roles
        roles = [
            ("ROLE-EMP", "Employee", "Standard user"),
            ("ROLE-MGR", "Line Manager", "Operational approval"),
            ("ROLE-DIR", "Department Director", "Executive approval"),
            ("ROLE-CTL", "Finance Controller", "Financial sign-off"),
            ("ROLE-SEC", "SecOps Lead", "Security incident escalation")
        ]
        for r_id, r_label, r_desc in roles:
            self.graph.add_node(r_id, type="Role", label=r_label, description=r_desc)

        # 3. Policy Sections & Rules
        # --- Finance Rules ---
        self.graph.add_node("SEC-FIN-01", type="Section", label="Expense Tiers & Thresholds", parent="POL-FIN-002")
        self.graph.add_edge("POL-FIN-002", "SEC-FIN-01", relation="HAS_SECTION")

        self.graph.add_node("RULE-FIN-TIER1", type="Rule", label="Low Value (< $100)", threshold=100.0, risk="LOW")
        self.graph.add_node("RULE-FIN-TIER2", type="Rule", label="Moderate ($100 - $1,000)", threshold=1000.0, risk="MEDIUM")
        self.graph.add_node("RULE-FIN-TIER3", type="Rule", label="High (> $1,000)", threshold=999999.0, risk="HIGH")
        self.graph.add_node("RULE-FIN-NO-REC", type="Rule", label="Missing Receipt Rejection", risk="LOW")

        self.graph.add_edge("SEC-FIN-01", "RULE-FIN-TIER1", relation="ENFORCES_RULE")
        self.graph.add_edge("SEC-FIN-01", "RULE-FIN-TIER2", relation="ENFORCES_RULE")
        self.graph.add_edge("SEC-FIN-01", "RULE-FIN-TIER3", relation="ENFORCES_RULE")
        self.graph.add_edge("SEC-FIN-01", "RULE-FIN-NO-REC", relation="ENFORCES_RULE")

        # Action & Approver edges
        self.graph.add_node("ACT-AUTO-APPROVE", type="Action", label="Auto Approve & Submit")
        self.graph.add_node("ACT-MGR-APPROVE", type="Action", label="Route to Line Manager")
        self.graph.add_node("ACT-DUAL-APPROVE", type="Action", label="Route to Director & Controller")
        self.graph.add_node("ACT-REJECT-CLAIM", type="Action", label="Reject Claim")

        self.graph.add_edge("RULE-FIN-TIER1", "ACT-AUTO-APPROVE", relation="TRIGGERS_ACTION")
        self.graph.add_edge("RULE-FIN-TIER2", "ACT-MGR-APPROVE", relation="TRIGGERS_ACTION")
        self.graph.add_edge("ACT-MGR-APPROVE", "ROLE-MGR", relation="REQUIRES_APPROVER")

        self.graph.add_edge("RULE-FIN-TIER3", "ACT-DUAL-APPROVE", relation="TRIGGERS_ACTION")
        self.graph.add_edge("ACT-DUAL-APPROVE", "ROLE-DIR", relation="REQUIRES_APPROVER")
        self.graph.add_edge("ACT-DUAL-APPROVE", "ROLE-CTL", relation="REQUIRES_APPROVER")

        self.graph.add_edge("RULE-FIN-NO-REC", "ACT-REJECT-CLAIM", relation="TRIGGERS_ACTION")

        # --- IT Rules ---
        self.graph.add_node("SEC-IT-01", type="Section", label="Incident Classification", parent="POL-IT-003")
        self.graph.add_edge("POL-IT-003", "SEC-IT-01", relation="HAS_SECTION")

        self.graph.add_node("RULE-IT-SEV1", type="Rule", label="Critical Outage (SEV-1)", sla="15 mins", risk="HIGH")
        self.graph.add_node("RULE-IT-SEV2", type="Rule", label="Major Disruption (SEV-2)", sla="2 hours", risk="MEDIUM")
        self.graph.add_node("RULE-IT-SEV3", type="Rule", label="Minor Support (SEV-3)", sla="24 hours", risk="LOW")

        self.graph.add_edge("SEC-IT-01", "RULE-IT-SEV1", relation="ENFORCES_RULE")
        self.graph.add_edge("SEC-IT-01", "RULE-IT-SEV2", relation="ENFORCES_RULE")
        self.graph.add_edge("SEC-IT-01", "RULE-IT-SEV3", relation="ENFORCES_RULE")

        self.graph.add_node("ACT-SECOPS-ALERT", type="Action", label="PagerDuty SecOps Escalation")
        self.graph.add_node("ACT-TICKET-STANDARD", type="Action", label="Create Standard Ticket")

        self.graph.add_edge("RULE-IT-SEV1", "ACT-SECOPS-ALERT", relation="TRIGGERS_ACTION")
        self.graph.add_edge("ACT-SECOPS-ALERT", "ROLE-SEC", relation="REQUIRES_APPROVER")
        self.graph.add_edge("RULE-IT-SEV3", "ACT-TICKET-STANDARD", relation="TRIGGERS_ACTION")

    def query_expense_approval_chain(self, amount: float, has_receipt: bool = True) -> Dict[str, Any]:
        """
        Multi-hop graph traversal to find the exact rule, action, and required approvers.
        """
        if not has_receipt:
            return {
                "rule_id": "RULE-FIN-NO-REC",
                "rule_label": "Missing Receipt Rejection",
                "action": "ACT-REJECT-CLAIM",
                "action_label": "Reject Claim",
                "approvers": [],
                "risk": "LOW",
                "policy_citation": "[POL-FIN-002:Sec3]",
                "traversal_path": ["POL-FIN-002", "SEC-FIN-01", "RULE-FIN-NO-REC", "ACT-REJECT-CLAIM"]
            }

        if amount < 100.0:
            rule_id = "RULE-FIN-TIER1"
        elif amount <= 1000.0:
            rule_id = "RULE-FIN-TIER2"
        else:
            rule_id = "RULE-FIN-TIER3"

        rule_data = self.graph.nodes[rule_id]
        
        # Traverse out from rule to action
        actions = [target for _, target, d in self.graph.out_edges(rule_id, data=True) if d.get("relation") == "TRIGGERS_ACTION"]
        action_id = actions[0] if actions else "UNKNOWN_ACTION"
        action_label = self.graph.nodes[action_id].get("label", action_id)

        # Traverse out from action to required approver roles
        approvers = [
            self.graph.nodes[target].get("label", target)
            for _, target, d in self.graph.out_edges(action_id, data=True)
            if d.get("relation") == "REQUIRES_APPROVER"
        ]

        return {
            "rule_id": rule_id,
            "rule_label": rule_data.get("label"),
            "action": action_id,
            "action_label": action_label,
            "approvers": approvers,
            "risk": rule_data.get("risk"),
            "policy_citation": "[POL-FIN-002:Sec1]",
            "traversal_path": ["POL-FIN-002", "SEC-FIN-01", rule_id, action_id] + approvers
        }

    def render_graph_image(self) -> str:
        """
        Renders the NetworkX knowledge graph into a clean base64 image for Streamlit/Web UI.
        """
        plt.figure(figsize=(10, 6), dpi=150)
        pos = nx.spring_layout(self.graph, seed=42, k=0.8)

        # Node colors by type
        color_map = []
        for n, d in self.graph.nodes(data=True):
            ntype = d.get("type", "")
            if ntype == "Policy":
                color_map.append("#93C5FD")  # blue
            elif ntype == "Section":
                color_map.append("#FDE047")  # yellow
            elif ntype == "Rule":
                color_map.append("#FCA5A5")  # red
            elif ntype == "Action":
                color_map.append("#86EFAC")  # green
            elif ntype == "Role":
                color_map.append("#D8B4FE")  # purple
            else:
                color_map.append("#CBD5E1")  # grey

        labels = {n: self.graph.nodes[n].get("label", n) for n in self.graph.nodes()}

        nx.draw_networkx_nodes(self.graph, pos, node_color=color_map, node_size=1800, alpha=0.9)
        nx.draw_networkx_edges(self.graph, pos, arrowstyle="->", arrowsize=14, edge_color="#94A3B8", width=1.5)
        nx.draw_networkx_labels(self.graph, pos, labels, font_size=7, font_weight="bold", font_color="#0F172A")

        plt.title("Enterprise Governance Knowledge Graph (GraphRAG)", fontsize=12, fontweight="bold", pad=12)
        plt.axis("off")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close()
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        return f"data:image/png;base64,{img_b64}"
