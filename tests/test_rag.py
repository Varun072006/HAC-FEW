"""
Unit and Integration tests for RAG Chunker and Hybrid Policy Retriever.
"""
import pytest
from core.rag.chunker import PolicyDocumentParser, load_all_policy_chunks
from core.rag.retriever import HybridPolicyRetriever


def test_chunking_metadata_and_sections():
    chunks = load_all_policy_chunks("data/policies")
    assert len(chunks) >= 3

    # Check HR policy chunk
    hr_chunks = [c for c in chunks if c.doc_id == "POL-HR-001"]
    assert len(hr_chunks) >= 1
    assert any("Section 1" in c.section_name for c in hr_chunks)
    assert hr_chunks[0].department == "hr"
    assert "hr_rep" in hr_chunks[0].allowed_roles


def test_expense_policy_retrieval():
    retriever = HybridPolicyRetriever("data/policies", confidence_threshold=0.08)
    
    # Query expense limits
    res = retriever.retrieve("What is the approval threshold for expenses over 1000 dollars?", user_role="employee")
    assert not res.abstain
    assert len(res.results) > 0
    top = res.results[0]
    assert top.doc_id == "POL-FIN-002"
    assert "Section 1" in top.section_name
    assert any("POL-FIN-002" in cit for cit in res.citations)
    assert "<policy_data" in res.context_for_prompt


def test_it_incident_severity_retrieval():
    retriever = HybridPolicyRetriever("data/policies", confidence_threshold=0.08)
    res = retriever.retrieve("What SLA is required for Severity 1 Critical company-wide outage?", user_role="it_admin")
    assert not res.abstain
    top = res.results[0]
    assert top.doc_id == "POL-IT-003"
    assert "Severity 1" in top.content


def test_role_filtered_access_denial():
    retriever = HybridPolicyRetriever("data/policies", confidence_threshold=0.08)
    # Search with a department restricted role
    res = retriever.retrieve("hardware refresh disposal rules", user_role="guest_role")
    # guest_role is not in allowed_roles for POL-IT-003
    assert res.abstain
    assert "No accessible policy documents found" in res.escalation_reason


def test_low_confidence_abstention():
    retriever = HybridPolicyRetriever("data/policies", confidence_threshold=0.50)
    # Query completely unrelated text
    res = retriever.retrieve("astrophysics quantum gravitation orbital mechanics", user_role="employee")
    assert res.abstain
    assert "below threshold" in res.escalation_reason
