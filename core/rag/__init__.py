"""
RAG Engine module:
- Section-based chunking (300-500 words, 10% overlap)
- Metadata preservation (document, section, department, access_role)
- Hybrid retrieval (dense embeddings + keyword search)
- Role-filtered access control
- Citation generation and confidence threshold abstention
"""
from core.rag.chunker import PolicyChunk, PolicyDocumentParser, load_all_policy_chunks
from core.rag.retriever import HybridPolicyRetriever, RetrievalResult, RAGQueryResponse

__all__ = [
    "PolicyChunk",
    "PolicyDocumentParser",
    "load_all_policy_chunks",
    "HybridPolicyRetriever",
    "RetrievalResult",
    "RAGQueryResponse"
]
