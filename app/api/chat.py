import json
import logging
import re
import time
from urllib.parse import urlparse
from typing import List, Dict, Any, AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import httpx

from core.db import get_db
from sqlalchemy.orm import Session
from core.models import Project, ApiRequestLog, AllowedDomain
from core.config import settings
from core.app_settings import get_all_settings
from ingestion.embedding import EmbeddingService
from retrieval.engine import RetrievalEngine
from retrieval.reranker import CrossEncoderService

logger = logging.getLogger(__name__)

# Note: In a production app, the reranker should probably be loaded on startup and attached to app state,
# but for this script we load it lazily or globally.
try:
    reranker_service = CrossEncoderService()
except Exception as e:
    logger.error(f"Failed to load CrossEncoder: {e}")
    reranker_service = None

router = APIRouter(prefix="/api", tags=["chat"])

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    
SYSTEM_PROMPT = (
    f"You are the {settings.project_name}, a friendly support chatbot that helps employees.\n\n"
    "HOW TO ANSWER:\n"
    "- Keep answers SHORT and simple: usually 1-3 sentences, or at most a few short bullet "
    "points. Never write long essays.\n"
    "- Write for a NON-TECHNICAL corporate user. Do NOT mention technology, frameworks, "
    "databases, servers, code or internal system architecture unless the user explicitly asks "
    "about them.\n"
    "- Be warm, clear and practical. Tell the user what to do next.\n"
    "- Use only the information given to answer. Do not invent facts.\n"
    "- You are STATELESS and have NO memory of earlier chats. Never say or imply you were "
    "'previously', 'earlier' or 'already' discussing a topic unless it literally appears under "
    "'Previous Conversation' below.\n"
    "- If the user only greets you or makes small talk, reply with a brief, friendly greeting and "
    "ask how you can help. Do NOT bring up specific policies, leave types, holidays or other topics "
    "unless the user asks about them.\n"
    "- If the user reports a problem (for example a missing option or no access) and the answer "
    "is available, give the simple reason or next step — for example, projects and access are "
    "usually assigned by their manager or HR.\n"
    "- If you genuinely do not have the information, reply briefly: \"I don't have information "
    f"on that. Please raise your query at {settings.support_email} and the team will help you.\"\n"
    "- Never mention the words 'context', 'documents' or 'segments' to the user.\n"
    "- Reply directly. Do NOT start with fillers like \"Here is a short answer\", \"Based on "
    "the information\" or restate the question — just answer.\n\n"
    "FORMATTING:\n"
    "- You may use Markdown: **bold**, bullet lists, and tables.\n"
    "- When comparing several items or listing structured values (limits, dates, amounts, "
    "categories), prefer a compact Markdown table over prose.\n"
    "- When the user asks for a chart or graph AND you have numeric values to show, output a "
    "fenced code block with language `chart` containing only JSON shaped like "
    '{"type": "bar", "title": "...", "labels": ["A", "B"], "series": [{"name": "...", '
    '"data": [1, 2]}]} — "type" may be "bar", "line" or "donut". Use only real numbers from '
    "the information given; if you have no numbers, say so instead of inventing data."
)


async def stream_ollama(prompt: str, model: str = None) -> AsyncGenerator[str, None]:
    """Streams response from Ollama using httpx. Yields SSE format strings."""
    url = f"{settings.ollama_base_url}/api/chat"

    payload = {
        "model": model or settings.default_generation_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        # Keep the chat model resident so it isn't reloaded (and swapped against the
        # embedding model) on every request — model reloads are the main source of the
        # long dead-time before the first token.
        "keep_alive": "30m",
        "options": {
            "temperature": 0.3,   # consistent, less rambly
            "top_p": 0.9,
            "num_predict": 400    # hard cap so answers stay short
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload, timeout=60.0) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    if chunk:
                        data = json.loads(chunk)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            # Format as Server-Sent Events
                            yield f"data: {json.dumps({'content': content})}\n\n"
                            
                yield "data: [DONE]\n\n"
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadError) as e:
        logger.error(f"Ollama API Error: {e}")
        # Custom fallback logic per user request
        fallback_message = f"System is updating or something related to it. Please contact {settings.support_email} for any query or update."
        yield f"data: {json.dumps({'content': fallback_message})}\n\n"
        yield "data: [DONE]\n\n"

# SSE headers shared by every streaming response from this endpoint.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Disable response buffering in nginx-style proxies so tokens flush live.
    "X-Accel-Buffering": "no",
}

# A message is "small talk" only when the WHOLE thing is a greeting/thanks — so
# "hi" matches but "hi, what is the leave policy?" does not (it has a real question).
_GREETING_RE = re.compile(
    r"^[\s\W]*(hi+|hey+|hello+|helo+|hii+|yo|hola|namaste|greetings|"
    r"good\s*(morning|afternoon|evening|day))([\s\W]+(there|team|all|everyone))?[\s\W]*$",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"^[\s\W]*(thanks?|thank\s*you|thankyou|thx|ty|ok(ay)?|cool|great|nice|"
    r"bye|goodbye|see\s*you|no\s*thanks?)[\s\W]*$",
    re.IGNORECASE,
)


def smalltalk_reply(text: str) -> Optional[str]:
    """Return a canned reply for a pure greeting / closing, else None.

    Answering these directly stops a bare "hi" from triggering retrieval, which
    would otherwise pull unrelated KB chunks and let the model invent a topic
    (e.g. "...we were talking about sandwich leave").
    """
    if _GREETING_RE.match(text):
        return f"Hello! 👋 I'm the {settings.project_name}. How can I help you today?"
    if _CLOSING_RE.match(text):
        return "Happy to help! Let me know if there's anything else you need."
    return None


async def stream_static(text: str) -> AsyncGenerator[str, None]:
    """Emit a fixed message in the same SSE shape the widget expects."""
    yield f"data: {json.dumps({'content': text})}\n\n"
    yield "data: [DONE]\n\n"


def request_origin(request: Request) -> str:
    """Which site called us: scheme://host from Origin (or Referer), else 'direct'.

    Server-to-server callers (curl, backends) send neither header — those show up
    as 'direct' in the API monitor and are exempt from the domain whitelist,
    which is a browser-facing control.
    """
    raw = request.headers.get("origin") or request.headers.get("referer") or ""
    if not raw:
        return "direct"
    try:
        p = urlparse(raw)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return "direct"


def log_api_request(db: Session, request: Request, slug: str,
                    project: Optional[Project], status_code: int, started: float) -> None:
    """Append one API-monitor row. Never allowed to break the chat request."""
    try:
        db.add(ApiRequestLog(
            project_id=project.id if project else None,
            project_slug=project.slug if project else slug,
            path=str(request.url.path),
            method=request.method,
            origin=request_origin(request),
            client_ip=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:300],
            status_code=status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ))
        db.commit()
    except Exception as e:  # pragma: no cover - monitoring must never break chat
        logger.warning(f"API request logging failed: {e}")
        db.rollback()


@router.post("/{slug}/v1/chat/completions")
async def chat_completions(slug: str, req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    started = time.perf_counter()
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Bounded conversation memory: Keep only the last 5 messages to avoid blowing up context window
    recent_messages = req.messages[-5:]

    last_user_msg = next((m["content"] for m in reversed(recent_messages) if m["role"] == "user"), None)
    if not last_user_msg:
        raise HTTPException(status_code=400, detail="No user message found")

    # Find project
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        log_api_request(db, request, slug, None, 404, started)
        raise HTTPException(status_code=404, detail="Project not found")

    # Admin can switch a project off — its API and widget stop answering.
    if (project.status or "active") == "disabled":
        log_api_request(db, request, slug, project, 403, started)
        raise HTTPException(status_code=403, detail="This project is currently disabled.")

    platform = get_all_settings(db)

    # Domain whitelist (browser-facing): when enforced, calls from a non-whitelisted
    # Origin/Referer host are rejected. 'direct' (no origin) callers pass.
    if platform.get("domain_whitelist_enforced"):
        origin = request_origin(request)
        if origin != "direct":
            host = (urlparse(origin).hostname or "").lower()
            # 'docs.example.com' matches itself or a '*.example.com' entry.
            candidates = {host}
            parts = host.split(".")
            for i in range(1, len(parts) - 1):
                candidates.add("*." + ".".join(parts[i:]))
            allowed = db.query(AllowedDomain).filter(
                AllowedDomain.domain.in_(candidates),
                (AllowedDomain.project_id == None) | (AllowedDomain.project_id == project.id),  # noqa: E711
            ).first()
            if not allowed:
                log_api_request(db, request, slug, project, 403, started)
                raise HTTPException(
                    status_code=403,
                    detail=f"Domain '{host}' is not whitelisted for this chatbot.",
                )

    # Greeting / small-talk short-circuit: answer directly, skip retrieval + LLM.
    canned = smalltalk_reply(last_user_msg)
    if canned:
        log_api_request(db, request, slug, project, 200, started)
        return StreamingResponse(stream_static(canned), media_type="text/event-stream", headers=SSE_HEADERS)

    # Retrieve context. Embedding + cross-encoder reranking are blocking, CPU-heavy
    # work, so run them in a threadpool to avoid stalling the event loop (and any
    # other in-flight streams).
    def _retrieve() -> list:
        engine = RetrievalEngine(db, reranker=reranker_service)
        embedder = EmbeddingService()
        query_embedding = embedder.embed_text(last_user_msg)
        return engine.retrieve(
            project.id, last_user_msg, query_embedding, top_k=6,
            include_company=bool(platform.get("global_project_enabled", True)),
            cross_project=bool(platform.get("cross_project_linking", False)),
        )

    try:
        chunks = await run_in_threadpool(_retrieve)
    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        chunks = []

    # Log now (time-to-context) so the monitor sees the request even though the
    # answer is still streaming.
    log_api_request(db, request, slug, project, 200, started)

    if chunks:
        context_text = "\n\n".join([f"--- Context Segment ---\n{c.text}" for c in chunks])
    else:
        context_text = (
            "(No matching information was found in the knowledge base for this question.)"
        )

    # Construct the final prompt, injecting conversation history
    history_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in recent_messages[:-1]])

    prompt = f"""Context:
{context_text}

Previous Conversation:
{history_text or "(none)"}

User Question: {last_user_msg}

Answer the user's question using the Context above."""

    return StreamingResponse(
        stream_ollama(prompt),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
