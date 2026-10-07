import re
from typing import List, Dict, Any, Optional
from app.rag.models import Chunk, Document


class CodeAwareChunker:
    """
    Structure-aware and Code-aware chunker.
    Strictly preserves HCL blocks (resource "...", module "...") and SQL statements
    as whole atomic units. Splits markdown on structural headings.
    """

    def __init__(self, target_tokens: int = 350, max_tokens: int = 600, overlap_tokens: int = 40):
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimator (~4 chars per token)."""
        return max(len(text) // 4, 1)

    def chunk_document(self, doc: Document) -> List[Chunk]:
        """Split a document into code-aware semantic chunks."""
        raw_text = doc.content.strip()
        if not raw_text:
            return []

        # Split on Markdown headers (## or ###)
        sections = self._split_markdown_sections(raw_text)
        chunks: List[Chunk] = []

        chunk_counter = 0
        for sec_title, sec_body in sections:
            # Further split section if it contains atomic code blocks + prose
            sub_units = self._extract_atomic_units(sec_body)
            current_chunk_text = ""
            current_hcl: Optional[str] = None
            current_res_type: Optional[str] = None

            for unit_type, unit_content in sub_units:
                unit_tokens = self.estimate_tokens(unit_content)

                # If this is an atomic HCL / code block
                if unit_type == "code":
                    res_type_match = re.search(r'resource\s+"([^"]+)"', unit_content)
                    if res_type_match:
                        current_res_type = res_type_match.group(1)
                    current_hcl = unit_content

                    # If adding this code exceeds max_tokens and we already have prose, flush prose first
                    if current_chunk_text and (self.estimate_tokens(current_chunk_text) + unit_tokens > self.max_tokens):
                        chunks.append(self._create_chunk(
                            doc, f"{sec_title} (part {chunk_counter + 1})",
                            current_chunk_text.strip(), chunk_counter, None, None
                        ))
                        chunk_counter += 1
                        current_chunk_text = ""

                    # Add code block intact (NEVER split a resource block mid-way)
                    if current_chunk_text:
                        current_chunk_text += "\n\n" + unit_content
                    else:
                        current_chunk_text = unit_content

                else:
                    # Prose unit
                    if current_chunk_text and (self.estimate_tokens(current_chunk_text) + unit_tokens > self.target_tokens):
                        chunks.append(self._create_chunk(
                            doc, f"{sec_title} (part {chunk_counter + 1})",
                            current_chunk_text.strip(), chunk_counter, current_hcl, current_res_type
                        ))
                        chunk_counter += 1
                        # Maintain prose overlap if possible
                        words = current_chunk_text.split()
                        overlap = " ".join(words[-self.overlap_tokens:]) if len(words) > self.overlap_tokens else ""
                        current_chunk_text = f"{overlap}\n{unit_content}".strip()
                        current_hcl = None
                        current_res_type = None
                    else:
                        if current_chunk_text:
                            current_chunk_text += "\n\n" + unit_content
                        else:
                            current_chunk_text = unit_content

            if current_chunk_text.strip():
                chunks.append(self._create_chunk(
                    doc, sec_title, current_chunk_text.strip(),
                    chunk_counter, current_hcl, current_res_type
                ))
                chunk_counter += 1

        return chunks

    def _split_markdown_sections(self, text: str) -> List[tuple[str, str]]:
        """Splits markdown text into (heading_title, section_body) tuples."""
        lines = text.splitlines()
        sections: List[tuple[str, str]] = []
        current_title = "Overview"
        current_lines: List[str] = []

        for line in lines:
            header_match = re.match(r'^(#{1,4})\s+(.+)$', line)
            if header_match:
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                    current_lines = []
                current_title = header_match.group(2).strip()
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_title, "\n".join(current_lines).strip()))

        return sections if sections else [("Document", text)]

    def _extract_atomic_units(self, section_text: str) -> List[tuple[str, str]]:
        """
        Parses section text into prose blocks and atomic code blocks (```...```).
        Ensures code blocks stay completely intact.
        """
        units: List[tuple[str, str]] = []
        code_fence_pattern = re.compile(r'(```(?:hcl|terraform|sql)?\n.*?\n```)', re.DOTALL)
        parts = code_fence_pattern.split(section_text)

        for part in parts:
            p = part.strip()
            if not p:
                continue
            if p.startswith("```") and p.endswith("```"):
                units.append(("code", p))
            else:
                # Prose paragraph splits
                paragraphs = [para.strip() for para in p.split("\n\n") if para.strip()]
                for para in paragraphs:
                    units.append(("prose", para))

        return units if units else [("prose", section_text)]

    def _create_chunk(
        self,
        doc: Document,
        title: str,
        content: str,
        index: int,
        hcl_code: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> Chunk:
        # Detect resource type if not explicit
        if not resource_type:
            rt_match = re.search(r'resource\s+"([^"]+)"', content)
            if rt_match:
                resource_type = rt_match.group(1)

        chunk = Chunk(
            chunk_id=f"{doc.id}_chk_{index:03d}",
            doc_id=doc.id,
            domain=doc.domain,
            title=f"{doc.title} — {title}",
            content=content,
            hcl_code=hcl_code,
            resource_type=resource_type,
            provider=doc.provider,
            version=doc.version,
            metadata=doc.metadata,
            token_estimate=self.estimate_tokens(content),
        )
        chunk.content_hash = chunk.compute_hash()
        return chunk
