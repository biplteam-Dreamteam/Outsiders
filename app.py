import os
import sys
import time
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

# Ensure root in python path
sys.path.insert(0, os.path.abspath("."))
from src.pipeline import SupportCopilotPipeline

app = FastAPI(
    title="Grand Mobile Support Copilot API",
    description="Интеллектуальный сервис триажа, RAG и черновиков ответов для Grand Mobile (Decentrathon 6.0, Case 03)",
    version="1.0.0"
)

# Initialize pipeline instance once
pipeline = SupportCopilotPipeline()


class MessageItem(BaseModel):
    role: Optional[str] = "player"
    ts: Optional[str] = None
    text: Optional[str] = ""


class TicketRequest(BaseModel):
    ticket_id: Optional[str] = None
    kind: Optional[str] = "complaint"
    created_at: Optional[str] = None
    region: Optional[str] = None
    server_lang: Optional[str] = None
    lang: Optional[str] = None
    reporter_hash: Optional[str] = None
    reported_hash: Optional[str] = None
    reported_nick: Optional[str] = None
    rule_refs_raw: Optional[Any] = None
    images_count: Optional[int] = 0
    status: Optional[int] = 0
    messages: Optional[List[MessageItem]] = []


class ExtractedFacts(BaseModel):
    nickname: Optional[str] = None
    rule_refs: List[str] = []
    has_evidence: bool = False
    server: Optional[str] = None


class DraftReply(BaseModel):
    lang: str = "ru"
    text: str = ""
    cited: List[str] = []


class TriageResponse(BaseModel):
    lang: str
    category: str
    priority: str
    is_spam_or_duplicate: bool
    extracted: ExtractedFacts
    draft_reply: DraftReply
    needs_human: bool
    confidence: float
    reasons: List[str] = []


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "classifier_loaded": pipeline.classifier.is_trained(),
        "rules_indexed": len(pipeline.rag.get_valid_rules_dict())
    }


@app.get("/")
def index():
    return {
        "service": "Grand Mobile Support Copilot",
        "case": "Case 03 (Decentrathon 6.0)",
        "docs_url": "/docs"
    }


@app.post("/triage", response_model=TriageResponse)
async def triage_endpoint(ticket: TicketRequest):
    """
    Основной боевой эндпоинт триажа тикета:
    - Определение языка текста
    - Классификация категории по таксономии
    - Определение приоритета (p0..p3)
    - Дедупликация и антиспам
    - Экстракция фактов (никнейм, нарушенные правила, доказательства, сервер)
    - Генерация черновика ответа со ссылками на правила
    - Защита от галлюцинаций и запрещенных обещаний (Guardrails)
    """
    ticket_dict = ticket.model_dump()
    result = await pipeline.triage_ticket_async(ticket_dict)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
