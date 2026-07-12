from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, delete, func
from core.models import DocumentChunk, ScopeEnum, DocTypeEnum


def build_scope_filter(project_id: int, include_company: bool = True, cross_project: bool = False):
    """Visibility filter shared by both search paths.

    include_company — merge the shared (company-scope) knowledge base in.
    cross_project   — let this project also search every other project's chunks
                      (the admin panel's "cross-project linking" toggle).
    """
    if cross_project:
        project_part = DocumentChunk.scope == ScopeEnum.project
    else:
        project_part = and_(
            DocumentChunk.scope == ScopeEnum.project,
            DocumentChunk.project_id == project_id,
        )
    if include_company:
        return or_(project_part, DocumentChunk.scope == ScopeEnum.company)
    return project_part


class VectorStore:
    def __init__(self, db: Session):
        self.db = db

    def upsert_chunks(self, chunks_data: List[Dict[str, Any]]):
        """
        Upsert a list of chunks into the database.
        Automatically generates a tsvector for Postgres FTS.
        """
        for data in chunks_data:
            chunk = DocumentChunk(**data)
            # Create tsvector for sparse search using the english dictionary
            chunk.tsv = func.to_tsvector('english', chunk.text)
            self.db.add(chunk)
        self.db.commit()

    def delete_by_document(self, document_id: int):
        """
        Delete all chunks associated with a specific document_id.
        """
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        self.db.execute(stmt)
        self.db.commit()

    def dense_search(
        self,
        project_id: int,
        query_embedding: List[float],
        top_k: int = 20,
        doc_types: Optional[List[DocTypeEnum]] = None,
        include_company: bool = True,
        cross_project: bool = False,
    ) -> List[DocumentChunk]:
        """
        Perform a dense vector search in-memory using numpy.
        Scope is controlled by the admin toggles (see build_scope_filter).
        """
        import numpy as np

        scope_filter = build_scope_filter(project_id, include_company, cross_project)

        conditions = [scope_filter]
        if doc_types:
            conditions.append(DocumentChunk.doc_type.in_(doc_types))

        # Fetch all candidate chunks
        stmt = select(DocumentChunk).where(and_(*conditions))
        chunks = list(self.db.execute(stmt).scalars().all())
        
        if not chunks:
            return []
            
        # Calculate cosine similarity in memory
        query_vec = np.array(query_embedding)
        norm_q = np.linalg.norm(query_vec)
        if norm_q == 0:
            return []
            
        scored_chunks = []
        for chunk in chunks:
            if not chunk.embedding:
                continue
            chunk_vec = np.array(chunk.embedding)
            norm_c = np.linalg.norm(chunk_vec)
            if norm_c == 0:
                continue
                
            similarity = np.dot(query_vec, chunk_vec) / (norm_q * norm_c)
            scored_chunks.append((similarity, chunk))
            
        # Sort by highest similarity
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        return [chunk for score, chunk in scored_chunks[:top_k]]

    def sparse_search(
        self,
        project_id: int,
        query_text: str,
        top_k: int = 20,
        doc_types: Optional[List[DocTypeEnum]] = None,
        include_company: bool = True,
        cross_project: bool = False,
    ) -> List[DocumentChunk]:
        """
        Perform a sparse keyword search using Postgres Full-Text Search (FTS).
        """
        scope_filter = build_scope_filter(project_id, include_company, cross_project)

        conditions = [scope_filter]
        if doc_types:
            conditions.append(DocumentChunk.doc_type.in_(doc_types))
            
        # Match TSVector against query
        ts_query = func.plainto_tsquery('english', query_text)
        conditions.append(DocumentChunk.tsv.op('@@')(ts_query))

        stmt = (
            select(DocumentChunk)
            .where(and_(*conditions))
            .order_by(func.ts_rank(DocumentChunk.tsv, ts_query).desc())
            .limit(top_k)
        )
        
        results = self.db.execute(stmt).scalars().all()
        return list(results)
