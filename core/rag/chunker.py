"""
Section-based Policy Document Chunker.
Requirements:
- Chunks by Markdown sections (300-500 words/tokens, ~10% overlap if section is long)
- Extracts and attaches metadata: doc_id, section_name, department, allowed_roles
- Generates unique deterministic chunk IDs: e.g. POL-HR-001:Sec1:c1
"""
import re
import os
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class PolicyChunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    section_name: str
    department: str
    allowed_roles: List[str]
    content: str
    token_count: int = 0


class PolicyDocumentParser:
    """Parses enterprise policy Markdown files into structured metadata-rich chunks."""

    @staticmethod
    def parse_metadata_header(text: str) -> Dict[str, Any]:
        doc_id_match = re.search(r"Document ID:\s*([^\n]+)", text)
        dept_match = re.search(r"Department:\s*([^\n]+)", text)
        roles_match = re.search(r"Access Role:\s*([^\n]+)", text)
        title_match = re.search(r"^#\s*([^\n]+)", text, re.MULTILINE)

        doc_id = doc_id_match.group(1).strip() if doc_id_match else "UNKNOWN-DOC"
        dept = dept_match.group(1).strip().lower() if dept_match else "general"
        roles_raw = roles_match.group(1).strip() if roles_match else "employee"
        roles = [r.strip().lower() for r in roles_raw.split(",")]
        title = title_match.group(1).strip() if title_match else "Enterprise Policy"

        return {
            "doc_id": doc_id,
            "doc_title": title,
            "department": dept,
            "allowed_roles": roles
        }

    @staticmethod
    def chunk_document(file_path: str, max_words: int = 400, overlap_words: int = 40) -> List[PolicyChunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        meta = PolicyDocumentParser.parse_metadata_header(content)
        
        # Split by markdown ## Section headers
        section_splits = re.split(r"(^##\s+Section\s+[^\n]+)", content, flags=re.MULTILINE)
        
        chunks: List[PolicyChunk] = []
        current_section_name = "Header Overview"
        
        i = 1
        while i < len(section_splits):
            header_candidate = section_splits[i].strip()
            if header_candidate.startswith("## Section"):
                current_section_name = header_candidate.lstrip("#").strip()
                section_body = section_splits[i + 1].strip() if i + 1 < len(section_splits) else ""
                i += 2
            else:
                section_body = header_candidate
                i += 1

            # Word-based chunking with overlap
            words = section_body.split()
            if not words:
                continue

            sec_id_slug = re.sub(r"[^a-zA-Z0-9]", "", current_section_name.split(":")[0])
            if len(words) <= max_words:
                chunk_id = f"{meta['doc_id']}:{sec_id_slug}:c1"
                chunks.append(PolicyChunk(
                    chunk_id=chunk_id,
                    doc_id=meta["doc_id"],
                    doc_title=meta["doc_title"],
                    section_name=current_section_name,
                    department=meta["department"],
                    allowed_roles=meta["allowed_roles"],
                    content=section_body,
                    token_count=len(words)
                ))
            else:
                step = max_words - overlap_words
                c_idx = 1
                for start in range(0, len(words), step):
                    chunk_words = words[start:start + max_words]
                    chunk_text = " ".join(chunk_words)
                    chunk_id = f"{meta['doc_id']}:{sec_id_slug}:c{c_idx}"
                    chunks.append(PolicyChunk(
                        chunk_id=chunk_id,
                        doc_id=meta["doc_id"],
                        doc_title=meta["doc_title"],
                        section_name=current_section_name,
                        department=meta["department"],
                        allowed_roles=meta["allowed_roles"],
                        content=chunk_text,
                        token_count=len(chunk_words)
                    ))
                    c_idx += 1
                    if start + max_words >= len(words):
                        break

        return chunks


def load_all_policy_chunks(policies_dir: str = "data/policies") -> List[PolicyChunk]:
    all_chunks = []
    if not os.path.exists(policies_dir):
        return []
    for file in os.listdir(policies_dir):
        if file.endswith(".md"):
            path = os.path.join(policies_dir, file)
            all_chunks.extend(PolicyDocumentParser.chunk_document(path))
    return all_chunks
