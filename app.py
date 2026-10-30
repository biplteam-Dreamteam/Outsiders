import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Setup path and logging
sys.path.insert(0, os.path.abspath("."))
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("copilot-api")

from src.pipeline import SupportCopilotPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Grand Mobile Support Copilot Service...")
    yield
    logger.info("Shutting down Grand Mobile Support Copilot Service...")
    try:
        await pipeline.llm.aclose()
    except Exception as e:
        logger.warning(f"Error during LLM client cleanup: {e}")


app = FastAPI(
    title="Grand Mobile Support Copilot API",
    description="Интеллектуальный сервис триажа, RAG и черновиков ответов для Grand Mobile (Decentrathon 6.0, Case 03)",
    version="1.0.0",
    lifespan=lifespan,
)

# Pipeline singleton
pipeline = SupportCopilotPipeline()


class MessageItem(BaseModel):
    role: str | None = "player"
    ts: str | None = None
    text: str | None = ""


class TicketRequest(BaseModel):
    ticket_id: str | None = None
    kind: str | None = "complaint"
    created_at: str | None = None
    region: str | None = None
    server_lang: str | None = None
    lang: str | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    reported_nick: str | None = None
    rule_refs_raw: Any | None = None
    images_count: int | None = 0
    status: int | None = 0
    messages: list[MessageItem] | None = []


class ExtractedFacts(BaseModel):
    nickname: str | None = None
    rule_refs: list[str] = []
    has_evidence: bool = False
    server: str | None = None


class DraftReply(BaseModel):
    lang: str = "ru"
    text: str = ""
    cited: list[str] = []


class TriageResponse(BaseModel):
    lang: str
    category: str
    priority: str
    is_spam_or_duplicate: bool
    extracted: ExtractedFacts
    draft_reply: DraftReply
    needs_human: bool
    confidence: float
    reasons: list[str] = []


@app.get("/health")
def health_check():
    try:
        return {
            "status": "healthy",
            "classifier_loaded": pipeline.classifier.is_trained(),
            "rules_indexed": len(pipeline.rag.get_valid_rules_dict()),
            "service": "Grand Mobile Support Copilot",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=500, content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/")
def index():
    return {
        "service": "Grand Mobile Support Copilot",
        "case": "Case 03 (Decentrathon 6.0)",
        "docs_url": "/docs",
        "health_url": "/health",
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
    try:
        ticket_dict = ticket.model_dump()
        result = await pipeline.triage_ticket_async(ticket_dict)
        return result
    except Exception as exc:
        logger.error(f"Unexpected error in triage: {exc}", exc_info=True)
        # Resilient fallback response guaranteeing compliance with the contract
        lang = ticket.lang or ticket.server_lang or "ru"
        return TriageResponse(
            lang=lang,
            category="complaint.other"
            if ticket.kind == "complaint"
            else "report.offtopic",
            priority="p2" if ticket.kind == "complaint" else "p3",
            is_spam_or_duplicate=False,
            extracted=ExtractedFacts(
                nickname=ticket.reported_nick,
                rule_refs=[],
                has_evidence=bool(ticket.images_count and ticket.images_count > 0),
                server=ticket.region or ticket.server_lang,
            ),
            draft_reply=DraftReply(
                lang=lang,
                text="Здравствуйте! Ваше обращение принято к рассмотрению. Ожидайте ответа администратора.",
                cited=[],
            ),
            needs_human=True,
            confidence=0.50,
            reasons=[f"Обращение направлено оператору для ручной проверки: {exc!s}"],
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
