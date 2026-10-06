"""
Hybrid Policy Document Retriever with Role-based Access Control (RBAC),
Confidence Thresholding, and Structured Citation Formatting.
"""
import os
import re
from typing import List, Dict, Any, Optional
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pydantic import BaseModel, Field

from core.rag.chunker import PolicyChunk, load_all_policy_chunks


class RetrievalResult(BaseModel):
    chunk_id: str
    doc_id: str
    section_name: str
    department: str
    score: float
    citation: str
    content: str


class RAGQueryResponse(BaseModel):
    query: str
    user_role: str
    department: Optional[str] = None
    results: List[RetrievalResult] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    top_score: float = 0.0
    abstain: bool = False
    escalation_reason: Optional[str] = None
    context_for_prompt: str = ""


class HybridPolicyRetriever:
    """
    Combines dense TF-IDF and keyword matching over segmented policy chunks.
    Enforces department and user-role access restrictions.
    """

    def __init__(self, policies_dir: str = "data/policies", confidence_threshold: float = 0.08):
        self.policies_dir = policies_dir
        self.confidence_threshold = confidence_threshold
        self.chunks: List[PolicyChunk] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self.reload()

    def reload(self):
        """Reloads and indexes all policy files from the directory."""
        self.chunks = load_all_policy_chunks(self.policies_dir)
        if not self.chunks:
            return

        corpus = [
            f"{c.doc_title} {c.section_name} {c.department} {c.content}"
            for c in self.chunks
        ]
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True
        )
        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)

    def retrieve(
        self,
        query: str,
        user_role: str = "employee",
        department: Optional[str] = None,
        top_k: int = 5
    ) -> RAGQueryResponse:
        """
        Executes role-filtered retrieval and formats citations.
        """
        if not self.chunks or self.vectorizer is None or self.tfidf_matrix is None:
            return RAGQueryResponse(
                query=query,
                user_role=user_role,
                department=department,
                abstain=True,
                escalation_reason="Knowledge base is empty or uninitialized."
            )

        # 1. Compute hybrid similarity scores
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        # 2. Filter by RBAC and Department rules
        candidate_indices = []
        user_role_lower = user_role.lower()
        dept_lower = department.lower() if department else None

        for idx, chunk in enumerate(self.chunks):
            # Check Role Permission: admin role has global view; otherwise user_role must be in allowed_roles
            role_allowed = (user_role_lower == "admin") or (user_role_lower in chunk.allowed_roles)
            dept_allowed = True
            if dept_lower:
                dept_allowed = (chunk.department == "general") or (chunk.department == dept_lower)

            if role_allowed and dept_allowed:
                candidate_indices.append((idx, scores[idx]))

        if not candidate_indices:
            return RAGQueryResponse(
                query=query,
                user_role=user_role,
                department=department,
                abstain=True,
                escalation_reason=f"No accessible policy documents found for role '{user_role}'."
            )

        # 3. Sort candidates by relevance
        candidate_indices.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidate_indices[:top_k]

        highest_score = float(top_candidates[0][1]) if top_candidates else 0.0

        # 4. Check confidence threshold
        if highest_score < self.confidence_threshold:
            return RAGQueryResponse(
                query=query,
                user_role=user_role,
                department=department,
                top_score=highest_score,
                abstain=True,
                escalation_reason=f"Confidence score {highest_score:.3f} is below threshold {self.confidence_threshold:.3f}. Escalating to human agent."
            )

        results: List[RetrievalResult] = []
        citations: List[str] = []
        prompt_context_blocks: List[str] = []

        for idx, score in top_candidates:
            c = self.chunks[idx]
            cit = f"[{c.doc_id} {c.section_name}]"
            citations.append(cit)
            results.append(RetrievalResult(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                section_name=c.section_name,
                department=c.department,
                score=float(score),
                citation=cit,
                content=c.content
            ))
            # Treat retrieved text strictly as untrusted data block
            prompt_context_blocks.append(
                f"<policy_data id=\"{c.chunk_id}\" citation=\"{cit}\">\n{c.content}\n</policy_data>"
            )

        context_string = "\n\n".join(prompt_context_blocks)

        return RAGQueryResponse(
            query=query,
            user_role=user_role,
            department=department,
            results=results,
            citations=list(set(citations)),
            top_score=highest_score,
            abstain=False,
            context_for_prompt=context_string
        )
