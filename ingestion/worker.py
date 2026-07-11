import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from sqlalchemy.orm import Session
from sqlalchemy import select

from core.db import SessionLocal
from core.models import IngestJob, JobStateEnum, Document, ScopeEnum, DocTypeEnum, StatusEnum
from ingestion.parser import DocumentParser
from ingestion.chunker import StructureAwareChunker
from ingestion.embedding import EmbeddingService
from retrieval.vector_store import VectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IngestionWorker:
    def __init__(self):
        self.parser = DocumentParser()
        self.chunker = StructureAwareChunker()
        self.embedder = EmbeddingService()

    def process_job(self, db: Session, job: IngestJob):
        logger.info(f"Processing job {job.id} for document {job.document_id}")
        
        # Mark as running
        job.state = JobStateEnum.running
        job.attempts += 1
        db.commit()

        try:
            document = db.query(Document).filter(Document.id == job.document_id).first()
            if not document:
                raise ValueError(f"Document {job.document_id} not found")

            pdf_path = document.source_path
            if not pdf_path:
                raise ValueError(f"Document {job.document_id} has no source_path")

            # 1. Parse with per-page engine routing (ocrplan.md). processing_mode
            # was decided at upload time from the user's hint + the pre-scan.
            mode = document.processing_mode or "standard"
            logger.info(f"Parsing document {pdf_path} (mode={mode})")
            parsed = self.parser.parse(pdf_path, mode=mode)
            pages = parsed["pages"]
            document.page_count = len(pages)

            engines = parsed.get("engines") or []
            document.ocr_engine = "mixed" if len(engines) > 1 else (engines[0] if engines else None)

            # 2. Chunk flowing text
            logger.info("Chunking document")
            all_chunks = []
            chunk_index = 0
            for page_data in pages:
                page_text = page_data["text"]
                if not page_text:
                    continue

                chunks = self.chunker.chunk_text(page_text)
                for chunk_text in chunks:
                    all_chunks.append({
                        "document_id": document.id,
                        "project_id": document.project_id,
                        "scope": document.scope,
                        "doc_type": document.doc_type,
                        "chunk_index": chunk_index,
                        "text": chunk_text,
                        "page": page_data["page"],
                        "token_count": self.chunker.count_tokens(chunk_text)
                    })
                    chunk_index += 1

            # 2b. Tables & figure descriptions become ATOMIC chunks — never split,
            # so a markdown table can't be shredded mid-row by the sentence chunker.
            for block in parsed.get("blocks", []):
                label = "Table" if block["kind"] == "table" else "Figure"
                block_text = f"[{label} — page {block['page']}]\n{block['text']}"
                all_chunks.append({
                    "document_id": document.id,
                    "project_id": document.project_id,
                    "scope": document.scope,
                    "doc_type": document.doc_type,
                    "chunk_index": chunk_index,
                    "text": block_text,
                    "page": block["page"],
                    "section": block["kind"],
                    "token_count": self.chunker.count_tokens(block_text)
                })
                chunk_index += 1

            if not all_chunks:
                logger.warning("No text extracted from document")
            else:
                # 3. Embed
                logger.info(f"Embedding {len(all_chunks)} chunks")
                texts = [c["text"] for c in all_chunks]
                embeddings = self.embedder.embed_batch(texts)
                
                for i, emb in enumerate(embeddings):
                    all_chunks[i]["embedding"] = emb

                # 4. Upsert (ACID delete old if versioned, but for now just upsert)
                logger.info("Upserting into VectorStore")
                vstore = VectorStore(db)
                vstore.delete_by_document(document.id)
                vstore.upsert_chunks(all_chunks)

            # Mark done
            job.state = JobStateEnum.done
            document.status = StatusEnum.active
            db.commit()
            logger.info(f"Job {job.id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}")
            job.state = JobStateEnum.failed
            job.error = str(e)
            db.commit()

    def run_loop(self, poll_interval: int = 5):
        logger.info("Starting ingestion worker loop...")
        while True:
            db: Session = SessionLocal()
            try:
                # Simple poll. In production, use FOR UPDATE SKIP LOCKED
                job = db.query(IngestJob).filter(IngestJob.state == JobStateEnum.queued).first()
                if job:
                    self.process_job(db, job)
                else:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(poll_interval)
            finally:
                db.close()

if __name__ == "__main__":
    worker = IngestionWorker()
    worker.run_loop()
