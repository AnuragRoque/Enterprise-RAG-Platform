<h1 align="center">Enterprise RAG Platform</h1>

<p align="center">
  <b>A multi-tenant document-intelligence system that answers natural-language questions strictly from your own documents — hybrid retrieval, cross-encoder reranking, grounded refusal, and real-time streaming from a fully local LLM.</b>
</p>

<p align="center">
  Built so the <b>retrieval pipeline does the heavy lifting</b> — six ranking stages hand the model near-perfect context, so it produces sharp, grounded answers <b>even from a small ~2B-class model running locally</b>. No GPU farm, no per-token API bill, no data leaving the network.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-async%20%2B%20SSE-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector%20%2B%20FTS-336791?logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  <img src="https://img.shields.io/badge/Ollama-Local%20LLM-black" alt="Ollama"/>
  <img src="https://img.shields.io/badge/RAG-Hybrid%20Retrieval-6E48AA" alt="RAG"/>
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License"/>
</p>

<p align="center">
  <img src="images/1.png" alt="Admin dashboard — document, category and user management" width="840"/>
  <br/><em>Admin dashboard — document, category, and user management</em>
</p>

<p align="center">
  <img src="images/2.png" alt="AI chat interface — grounded, streamed answers" width="840"/>
  <br/><em>Chat interface — natural-language answers, streamed token-by-token and grounded in source documents</em>
</p>

---

## Overview

Most "chat with your PDF" demos fall apart in a real organization: they can't tell which policy is authoritative, they leak one team's documents into another team's answers, and they cheerfully hallucinate when the answer simply isn't in the source material.

**Enterprise RAG Platform** is built for that reality. It ingests documents (including scanned PDFs via OCR), stores project- and company-scoped knowledge, retrieves evidence through **dense + sparse hybrid search**, fuses rankings with **RRF**, sharpens precision with a **cross-encoder**, trims redundancy with **MMR**, refuses to answer when evidence is weak, and streams grounded answers from a **locally hosted LLM** — with tenant isolation enforced in SQL, not left to the model's goodwill.

> **Core principle:** a better answer starts with better evidence.

---

## Key Features

- **Multi-tenant knowledge spaces** — project-private documents plus company-wide shared policies, isolated at the database layer
- **Hybrid retrieval** — dense semantic search **and** PostgreSQL full-text search, run in parallel
- **Reciprocal Rank Fusion (RRF)** — merges two incompatible ranking systems cleanly
- **Cross-encoder reranking** — re-reads *question + passage together* for precision
- **MMR diversification** — removes near-duplicate context so the model sees complementary evidence
- **Grounded refusal** — below a relevance threshold, the system declines instead of hallucinating
- **Background OCR ingestion** — non-blocking uploads with observable `queued → running → done` jobs
- **Sentence-aware, token-bounded chunking** — with overlap so answers that straddle a boundary aren't lost
- **Fully local inference** — embeddings and generation run on Ollama; no third-party API calls
- **OpenAI-compatible streaming API** — `/v1/chat/completions` with Server-Sent Events
- **XSS-safe Markdown rendering** — model output is escaped before it ever touches the DOM

---

## Architecture

Two journeys meet inside PostgreSQL: a document is **prepared once** on upload, then **read on every question**.

```mermaid
flowchart TB
    classDef store fill:#1f6feb,stroke:#0b3d91,color:#fff,font-weight:bold
    classDef ing fill:#0f2f24,stroke:#2ea043,color:#d2f5df
    classDef chat fill:#2d1b3d,stroke:#a371f7,color:#efe2ff

    subgraph ING["🗂️  INGESTION · once per document"]
        direction LR
        UP["Admin uploads<br/>PDF"] --> PR["Parse<br/>PyMuPDF + OCR"]
        PR --> CH["Chunk<br/>~600 tok / 90 overlap"]
        CH --> EM["Embed<br/>nomic-embed-text · 768-d"]
    end

    DB[("🐘  PostgreSQL<br/>pgvector + Full-Text Search<br/>chunks · vectors · project_id · scope")]

    subgraph CHAT["💬  CHAT · every question"]
        direction LR
        Q["User question"] --> QE["Embed<br/>(same model)"]
        QE --> HS["Hybrid search<br/>dense + sparse"]
        HS --> RRF["RRF fusion"]
        RRF --> RR["Cross-encoder<br/>rerank"]
        RR --> MMR["MMR<br/>diversify"]
        MMR --> GATE["Grounded-refusal<br/>gate"]
        GATE --> LLM["Local LLM<br/>via Ollama"]
        LLM --> ST["Stream to browser<br/>Server-Sent Events"]
    end

    EM --> DB
    DB --> HS

    class UP,PR,CH,EM ing
    class Q,QE,HS,RRF,RR,MMR,GATE,LLM,ST chat
    class DB store
```

---

## The Retrieval Funnel

Every question passes through a funnel that starts **wide** (don't lose the right evidence) and ends **narrow** (hand the model only what matters). This staged design is what lets a small local model punch far above its weight.

```mermaid
flowchart LR
    classDef s fill:#161b22,stroke:#30363d,color:#e6edf3

    A["Dense search<br/>cosine · top 20"] --> C["RRF fusion<br/>Σ 1/(60+rank)<br/>~40 candidates"]
    B["Sparse search<br/>Postgres FTS · top 20"] --> C
    C --> D["Cross-encoder rerank<br/>+ project-scope boost"]
    D --> E["MMR diversify<br/>λ = 0.7 · final 6 chunks"]
    E --> F["Refusal gate<br/>below threshold → decline"]
    F --> G(["6 razor-sharp<br/>context chunks"])

    class A,B,C,D,E,F,G s
```

| # | Stage | What it buys you |
|---|---|---|
| 1 | **Dense search** (meaning) | Catches paraphrases — *"time off"* ↔ *"annual leave"* |
| 2 | **Sparse search** (keywords) | Catches exact terms embeddings miss — policy codes, acronyms, IDs |
| 3 | **RRF fusion** | Merges both rankings without forcing incompatible scores onto one scale |
| 4 | **Cross-encoder rerank** | Reads question + chunk jointly for precision — run only on the shortlist |
| 5 | **MMR diversify** | Kills near-duplicates so 6 chunks cover 6 angles, not 1 restated 6× |
| 6 | **Grounded-refusal gate** | Weak evidence → a controlled *"I don't have that"* instead of a hallucination |

> **Two-stage by design:** the expensive cross-encoder never touches the full corpus — only the ~40 candidates that survive fusion. Broad recall stays cheap; final precision stays affordable.

---

## Multi-Tenant Isolation

The platform serves multiple applications from one deployment, each with private documents, alongside company-wide shared policies.

```text
Company Knowledge (shared, scope = company)
├── Leave Policy
├── Holiday Policy
└── Security Policy

Worklog Application            (slug: worklog)
├── Worklog SOP
└── Worklog Runbook

Vendor Management Application  (slug: vendor-management)
├── Vendor Onboarding Workflow
└── Vendor Management Runbook
```

A **Worklog Application** query may retrieve:

```text
Worklog documents  +  company-wide documents
```

…but **never** the Vendor Management Application's private documents. The boundary is enforced inside the database query, before ranking ever begins:

```sql
(scope = 'project' AND project_id = :current_project)
OR (scope = 'company')
```

> **The LLM is never treated as a security boundary.** Disallowed rows are filtered out in SQL, so another tenant's context can't even enter the prompt.

---

## Request Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as Chat API
    participant DB as PostgreSQL
    participant R as Cross-Encoder
    participant L as Ollama

    U->>API: Ask question
    API->>API: Resolve tenant + embed query
    par Dense search
        API->>DB: Vector similarity (scoped in SQL)
        DB-->>API: Candidates
    and Sparse search
        API->>DB: Full-text search (scoped in SQL)
        DB-->>API: Candidates
    end
    API->>API: RRF fusion
    API->>R: Rerank shortlist
    R-->>API: Relevance scores
    API->>API: MMR + refusal check
    alt Strong evidence
        API->>L: Grounded prompt
        loop Generation
            L-->>API: Token
            API-->>U: SSE stream
        end
    else Weak evidence
        API-->>U: Controlled fallback
    end
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | **Python**, **FastAPI** — async endpoints, threadpool offloading for CPU-heavy retrieval |
| Database | **PostgreSQL** — `pgvector` (dense) + Full-Text Search / `tsvector` (sparse) |
| PDF parsing | **PyMuPDF**, with **Tesseract** OCR fallback (`pdf2image`) for scanned pages |
| Chunking | **NLTK** sentence segmentation + **tiktoken** token budgeting, with overlap |
| Embeddings | **nomic-embed-text** via Ollama — local, 768-dimensional |
| Fusion | **Reciprocal Rank Fusion** |
| Reranking | **Cross-encoder** (`ms-marco-MiniLM-L-6-v2`) |
| Diversification | **Maximal Marginal Relevance** (λ = 0.7) |
| Generation | Local LLM via **Ollama** — temperature `0.3`, capped output, kept warm via `keep_alive` |
| Streaming | **Server-Sent Events** |
| Frontend | HTML / CSS / vanilla JS — embeddable chat widget with safe Markdown rendering |

---

## Engineering Highlights

The parts that took the real work:

- **Non-blocking ingestion** — uploads return instantly; a background worker owns parsing, OCR, chunking, and embedding, and exposes honest job state (`queued → running → done`, or `failed` with the error captured — nothing fails silently).
- **Async that stays responsive** — CPU-bound embedding and reranking are offloaded to a threadpool so one heavy request never freezes every other live chat.
- **Two-stage retrieval economics** — cheap recall over the whole corpus, expensive cross-encoder only on the fused shortlist.
- **Robust document handling** — OCR fallback for image-only pages, plus text normalization (de-hyphenation, whitespace collapsing) and page tagging for traceability.
- **Resilient embedding** — batched calls with retry + backoff so a transient Ollama hiccup doesn't kill a job.
- **Low perceived latency** — the model is kept warm (`keep_alive`), history is bounded to recent turns, and tokens stream to the browser as they're generated.
- **Prompt discipline** — a strict system prompt forces short, grounded, human answers and a controlled fallback when evidence is missing.
- **Clean re-ingestion** — re-uploading a document replaces its old chunks instead of duplicating them.

---

## Project Structure

```text
enterprise-rag-platform/
├── app/
│   ├── api/
│   │   ├── admin.py          # document upload + admin endpoints
│   │   └── chat.py           # chat orchestration, prompt assembly, SSE streaming
│   ├── models/
│   └── main.py
├── ingestion/
│   ├── worker.py             # background job processor
│   ├── parser.py             # PDF extraction + OCR fallback + normalization
│   ├── chunker.py            # sentence-aware, token-bounded chunking
│   └── embedding.py          # local embedding generation
├── retrieval/
│   ├── vector_store.py       # dense + sparse search (scoped in SQL)
│   ├── engine.py             # RRF fusion · project boost · refusal threshold
│   ├── reranker.py           # cross-encoder scoring
│   └── mmr.py                # diversity selection
├── static/
│   ├── admin.html            # admin UI
│   └── chatbot.js            # streaming chat widget + safe Markdown rendering
├── data/                     # uploaded documents (git-ignored)
├── images/                   # screenshots
├── .env.example
├── requirements.txt
└── README.md
```

---

## Getting Started

**Prerequisites:** Python 3.11+, PostgreSQL with the `pgvector` extension, and [Ollama](https://ollama.com).

```bash
# 1. Pull the local models
ollama pull nomic-embed-text
ollama pull llama3.2          # or any small local model you prefer

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment (database URL, Ollama host, etc.)
cp .env.example .env          # then edit the values

# 4. Run the API and the ingestion worker (separate processes)
uvicorn app.main:app --reload
python -m ingestion.worker
```

Open the admin UI, create a project, upload a PDF, wait for its job to read `done`, then ask a question in the chat widget.

---

## API

The chat endpoint is **OpenAI-compatible**, so existing client SDKs work with a base-URL swap.

**Chat completion**

```http
POST /api/{project_slug}/v1/chat/completions
Content-Type: application/json
```

```json
{
  "messages": [
    { "role": "user", "content": "What is the approval process?" }
  ]
}
```

Streaming response (Server-Sent Events):

```text
data: {"content":"The"}
data: {"content":" approval"}
data: {"content":" process"}
data: {"content":" requires..."}
data: [DONE]
```

**Upload a document**

```http
POST /api/admin/documents
Content-Type: multipart/form-data
```

```json
{
  "document_id": "…",
  "job_id": "…",
  "status": "queued"
}
```

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| Dense **+** sparse retrieval | Capture both meaning and exact terminology |
| RRF fusion | Merge incompatible ranking systems without brittle score normalization |
| Cross-encoder reranking | Recover precision after broad, recall-oriented retrieval |
| MMR | Trim repetitive context so the model sees complementary evidence |
| SQL-level scope filtering | Prevent cross-tenant leakage without trusting the model |
| Background ingestion | Keep OCR and embedding off the request path |
| Local inference | Full control over sensitive knowledge; no per-token API cost |
| SSE streaming | Cut perceived latency to first token |

---

## Challenges Solved

| Challenge | Solution |
|---|---|
| Scanned, image-only PDFs | OCR fallback (Tesseract) |
| Exact terms missed by embeddings | Sparse full-text retrieval |
| Paraphrases missed by keyword search | Dense semantic retrieval |
| Incompatible search score scales | RRF fusion |
| Weak first-stage precision | Cross-encoder reranking |
| Repetitive context | MMR diversification |
| Cross-tenant leakage risk | SQL-level scope filtering |
| Hallucination under weak evidence | Grounded-refusal threshold |
| Slow perceived generation | SSE token streaming + warm model |
| Expensive document processing | Background worker with job lifecycle |

---

## Evaluating Retrieval Quality

Retrieval is built to be measured, not assumed. Because each stage is independently switchable, quality can be attributed stage-by-stage with an ablation:

```text
dense only  →  sparse only  →  dense + sparse  →  + RRF  →  + cross-encoder  →  + MMR
```

Comparing recall and ranking metrics across these configurations shows whether each stage earns its place, rather than stacking components on faith.

---

## Performance & Optimizations

Designed for low latency on modest hardware:

- **Warm model** via `keep_alive` → fast time-to-first-token
- **Streaming** responses → immediate feedback instead of waiting for full generation
- **Bounded conversation history** → small, fast prompts
- **Two-stage retrieval** → the costly reranker runs on ~40 candidates, not the whole corpus
- **Batched embeddings** with retry/backoff → resilient, efficient ingestion
- **Threadpool offloading** → the async event loop stays responsive under load
- **Indexed search** → `pgvector` for dense similarity + GIN-indexed `tsvector` for full-text

---

## Security

- **Tenant isolation enforced in SQL** — disallowed documents never reach the prompt
- **Grounded refusal** — the model can't invent answers when evidence is missing
- **XSS-safe rendering** — model output is escaped before insertion into the DOM
- **Local inference** — sensitive documents never leave the network
- **Environment-based secrets** — configuration via `.env`, with an `.env.example` template

---

## What This Project Demonstrates

Production-oriented RAG and information-retrieval engineering: hybrid dense/sparse search, rank fusion, cross-encoder reranking, MMR diversification, grounded refusal, OCR document pipelines, multi-tenant data isolation, asynchronous background processing, local LLM deployment, and streaming AI interfaces on a FastAPI + PostgreSQL backend.

---

## Author

**Anurag Singh** — AI & Data Engineer focused on production RAG systems, retrieval engineering, NLP, local LLMs, and AI-backed applications.

- LinkedIn: https://linkedin.com/in/anurag2050
- GitHub: https://github.com/anuragroque

---

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE).

<p align="center"><em>A better answer starts with better evidence.</em></p>
