import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from core.models import DocumentChunk
from retrieval.vector_store import VectorStore
from retrieval.reranker import CrossEncoderService
from retrieval.mmr import maximal_marginal_relevance
from core.config import settings

logger = logging.getLogger(__name__)

def compute_rrf(ranked_lists: List[List[DocumentChunk]], k: int = 60) -> List[DocumentChunk]:
    """
    Reciprocal Rank Fusion (RRF).
    Fuses multiple ranked lists of chunks into a single ranked list.
    Score = sum(1 / (k + rank))
    """
    rrf_scores: Dict[int, float] = {}
    chunk_map: Dict[int, DocumentChunk] = {}
    
    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list):
            if chunk.id not in rrf_scores:
                rrf_scores[chunk.id] = 0.0
                chunk_map[chunk.id] = chunk
            # Rank is 0-indexed, so we add 1 for the formula
            rrf_scores[chunk.id] += 1.0 / (k + rank + 1)
            
    # Sort chunks by RRF score descending
    sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)
    return [chunk_map[cid] for cid in sorted_chunk_ids]

class RetrievalEngine:
    def __init__(self, db: Session, reranker: Optional[CrossEncoderService] = None):
        self.db = db
        self.vector_store = VectorStore(db)
        self.reranker = reranker

    def retrieve(
        self,
        project_id: int,
        query_text: str,
        query_embedding: List[float],
        top_k: int = 6,
        include_company: bool = True,
        cross_project: bool = False,
    ) -> List[DocumentChunk]:
        """
        Executes the full Phase 3 retrieval pipeline:
        1. Dense Search (pgvector)
        2. Sparse Search (FTS)
        3. Reciprocal Rank Fusion (RRF)
        4. Cross-Encoder Re-ranking
        5. Maximal Marginal Relevance (MMR)

        include_company / cross_project are the admin panel's global toggles
        ("Global knowledge base" / "Cross-project linking").
        """
        logger.info(f"Retrieving for project {project_id} - query: '{query_text}'")

        # 1 & 2. Multi-search (retrieve more chunks initially for filtering)
        initial_k = 20
        dense_results = self.vector_store.dense_search(
            project_id, query_embedding, top_k=initial_k,
            include_company=include_company, cross_project=cross_project,
        )
        sparse_results = self.vector_store.sparse_search(
            project_id, query_text, top_k=initial_k,
            include_company=include_company, cross_project=cross_project,
        )
        
        # 3. Fuse
        fused_results = compute_rrf([dense_results, sparse_results])
        logger.info(f"RRF fused down to {len(fused_results)} unique chunks")
        
        if not fused_results:
            return []
            
        # If reranker isn't initialized, we just return top_k of RRF
        if not self.reranker:
            return fused_results[:top_k]
            
        # 4. Re-rank
        chunk_texts = [c.text for c in fused_results]
        rerank_scores = self.reranker.score_pairs(query_text, chunk_texts)
        
        # Apply a tiny boost to project-scope chunks to break ties against company-scope
        for i, chunk in enumerate(fused_results):
            if chunk.scope.name == 'project':
                rerank_scores[i] *= 1.05
                
        # 5. Diversify with MMR
        embeddings = [c.embedding for c in fused_results]
        
        # We pass the rerank_scores as the relevance metric for MMR
        selected_indices = maximal_marginal_relevance(
            query_embedding=query_embedding,
            chunk_embeddings=embeddings,
            relevance_scores=rerank_scores,
            top_k=top_k,
            lambda_param=0.7  # 70% relevance, 30% diversity
        )
        
        final_chunks = [fused_results[i] for i in selected_indices]
        
        # Grounded Refusal Check: only refuse when the best match is genuinely poor.
        # The threshold is conservative because the cross-encoder scores many relevant
        # passages negatively; refusing too eagerly leaves the LLM with no context and
        # makes it reply "I don't know" to normal questions.
        if selected_indices and rerank_scores[selected_indices[0]] < settings.refusal_score_threshold:
            logger.warning(
                "Top chunk score %.2f below refusal threshold %.2f. Grounded refusal triggered.",
                rerank_scores[selected_indices[0]], settings.refusal_score_threshold,
            )
            return []
            
        return final_chunks
