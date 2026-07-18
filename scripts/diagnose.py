"""
Diagnostic: is the chatbot's problem in RETRIEVAL or GENERATION?

Run from the project root:
    python scripts/diagnose.py demo-project "your test question here"

It checks, in order:
  1. Does the project exist?
  2. How many documents / chunks does it have, and how many chunks actually
     have an embedding (NULL embedding = ingestion never finished)?
  3. Does the reranker load?
  4. Run the REAL retrieval pipeline and print the chunks it returns, so you
     can see exactly what the LLM is being given as context.
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from core.db import SessionLocal
from core.models import Project, Document, DocumentChunk, IngestJob, JobStateEnum


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "demo-project"
    question = sys.argv[2] if len(sys.argv) > 2 else "What is the leave policy?"

    db = SessionLocal()

    print("=" * 70)
    print(f"PROJECT: {slug}")
    print(f"QUESTION: {question}")
    print("=" * 70)

    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        print("❌ Project not found. Available projects:")
        for p in db.query(Project).all():
            print(f"   - {p.slug}")
        return
    print(f"✅ Project found (id={project.id})")

    # ---- Document + chunk health -------------------------------------------
    docs = db.query(Document).filter(Document.project_id == project.id).all()
    print(f"\nDocuments in this project: {len(docs)}")
    for d in docs:
        print(f"   - [{d.id}] {d.title}  status={d.status}  scope={d.scope}")

    # Failed/queued ingest jobs (chunks may be missing/incomplete)
    bad_jobs = (
        db.query(IngestJob)
        .filter(IngestJob.state.in_([JobStateEnum.failed, JobStateEnum.queued, JobStateEnum.running]))
        .all()
    )
    if bad_jobs:
        print("\n⚠️  Ingest jobs NOT done:")
        for j in bad_jobs:
            print(f"   - job {j.id} doc={j.document_id} state={j.state} error={j.error}")

    total_chunks = db.query(func.count(DocumentChunk.id)).scalar()
    null_emb = (
        db.query(func.count(DocumentChunk.id))
        .filter(DocumentChunk.embedding.is_(None))
        .scalar()
    )
    print(f"\nTotal chunks (all projects): {total_chunks}")
    print(f"Chunks with NO embedding:     {null_emb}  "
          f"{'❌ dense search will skip these!' if null_emb else '✅'}")

    # Chunks visible to THIS project (project-scope + company-scope)
    from retrieval.vector_store import VectorStore
    from core.models import ScopeEnum
    from sqlalchemy import or_, and_
    scope_filter = or_(
        and_(DocumentChunk.scope == ScopeEnum.project, DocumentChunk.project_id == project.id),
        DocumentChunk.scope == ScopeEnum.company,
    )
    visible = db.query(func.count(DocumentChunk.id)).filter(scope_filter).scalar()
    print(f"Chunks visible to '{slug}':    {visible}  "
          f"{'❌ NOTHING to retrieve from!' if not visible else '✅'}")

    # ---- Reranker load check -----------------------------------------------
    print("\nLoading reranker...")
    try:
        from retrieval.reranker import CrossEncoderService
        reranker = CrossEncoderService()
        print("✅ Reranker loaded")
    except Exception as e:
        reranker = None
        print(f"❌ Reranker FAILED to load: {e}")
        print("   (pipeline falls back to raw RRF order — lower quality)")

    # ---- Run the real retrieval --------------------------------------------
    print("\nRunning real retrieval pipeline...")
    try:
        from ingestion.embedding import EmbeddingService
        from retrieval.engine import RetrievalEngine

        embedder = EmbeddingService()
        q_emb = embedder.embed_text(question)
        engine = RetrievalEngine(db, reranker=reranker)
        chunks = engine.retrieve(project.id, question, q_emb, top_k=6)

        print(f"\nRetrieved {len(chunks)} chunks for the LLM:")
        if not chunks:
            print("   ❌ EMPTY — the LLM gets '(No matching information)'.")
            print("      Either nothing was ingested, or the refusal threshold is too high.")
        for i, c in enumerate(chunks):
            preview = c.text[:160].replace("\n", " ")
            print(f"\n   [{i+1}] doc={c.document_id} page={c.page} scope={c.scope.name}")
            print(f"       {preview}...")
    except Exception as e:
        import traceback
        print(f"❌ Retrieval crashed: {e}")
        traceback.print_exc()

    db.close()
    print("\n" + "=" * 70)
    print("READING THE RESULT:")
    print("  - Chunks returned & relevant  -> retrieval is fine; the problem is the")
    print("    SHORT-answer system prompt + num_predict cap in app/api/chat.py.")
    print("  - 0 chunks / NULL embeddings  -> ingestion problem; re-run the worker.")
    print("  - Chunks returned but WRONG    -> retrieval/threshold tuning.")
    print("=" * 70)


if __name__ == "__main__":
    main()
