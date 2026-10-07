import os
import glob
import hashlib
from typing import List, Dict, Any, Set, Tuple
import structlog

from app.rag.models import Document, Chunk
from app.rag.ingestion.chunker import CodeAwareChunker

logger = structlog.get_logger(__name__)


class IngestionPipeline:
    """
    Ingestion pipeline supporting markdown & code parsing,
    SHA-256 deduplication, and incremental updating.
    """

    def __init__(self, chunker: CodeAwareChunker | None = None):
        self.chunker = chunker or CodeAwareChunker()
        self.seen_hashes: Set[str] = set()

    @staticmethod
    def compute_file_hash(filepath: str) -> str:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def ingest_file(
        self,
        filepath: str,
        domain: str = "terraform_aws",
        provider: str = "aws",
        version: str = "5.0",
    ) -> Tuple[Document, List[Chunk]]:
        """Parse a local documentation file and generate code-aware chunks."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        file_hash = self.compute_file_hash(filepath)
        filename = os.path.basename(filepath)
        doc_id = f"doc_{os.path.splitext(filename)[0]}"

        # Title from first header or filename
        title = filename.replace(".md", "").replace("_", " ").title()
        for line in content.splitlines()[:5]:
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        doc = Document(
            id=doc_id,
            domain=domain,
            title=title,
            source_url=f"file://{filepath}",
            provider=provider,
            version=version,
            content=content,
            metadata={
                "filepath": filepath,
                "file_hash": file_hash,
                "filename": filename,
            }
        )

        all_chunks = self.chunker.chunk_document(doc)

        # Deduplication: filter out any chunks whose content hash was already processed
        deduped_chunks: List[Chunk] = []
        for chk in all_chunks:
            if chk.content_hash not in self.seen_hashes:
                self.seen_hashes.add(chk.content_hash)
                deduped_chunks.append(chk)
            else:
                logger.debug("Skipping duplicate chunk", chunk_id=chk.chunk_id)

        logger.info(
            "Document ingested",
            doc_id=doc.id,
            total_chunks=len(all_chunks),
            unique_chunks=len(deduped_chunks),
        )
        return doc, deduped_chunks

    def ingest_directory(
        self,
        directory: str,
        domain: str = "terraform_aws",
        provider: str = "aws",
        version: str = "5.0",
    ) -> Tuple[List[Document], List[Chunk]]:
        """Batch ingest all markdown files in a directory."""
        docs: List[Document] = []
        chunks: List[Chunk] = []

        files = glob.glob(os.path.join(directory, "**/*.md"), recursive=True)
        for f in sorted(files):
            try:
                doc, doc_chunks = self.ingest_file(f, domain=domain, provider=provider, version=version)
                docs.append(doc)
                chunks.extend(doc_chunks)
            except Exception as e:
                logger.error("Failed to parse file", filepath=f, error=str(e))

        return docs, chunks
