import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, ORJSONResponse
from pydantic import BaseModel

# Setup path and logging
sys.path.insert(0, os.path.abspath("."))
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("copilot-api")

from src.crm_connectors import CRMConnectorManager
from src.guardrails import sanitize_draft
from src.pipeline import SupportCopilotPipeline
from src.rag_engine import RuleValidator
from src.rule_manager import (
    DEFAULT_RULES_PATH,
    get_active_rules_path,
    parse_rules_content,
    save_active_rules,
)

# Initialize RuleValidator singleton for Level 2 & 3 verification
rule_validator = RuleValidator()

# Initialize B2B CRM & Auto-Reply Manager
crm_manager = CRMConnectorManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Via Automation Enterprise Service...")
    yield
    logger.info("Shutting down Via Automation Enterprise Service...")
    try:
        await pipeline.llm.aclose()
    except Exception as e:
        logger.warning(f"Error during LLM client cleanup: {e}")


app = FastAPI(
    title="Via Automation Enterprise Support API",
    description="Универсальный автономный сервис поддержки, триажа и динамической базы знаний («Via автоматизация»)",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

# Pipeline singleton
pipeline = SupportCopilotPipeline()


class MessageItem(BaseModel):
    model_config = {"extra": "allow"}
    role: str | None = "player"
    ts: str | None = None
    text: str | None = ""


class TicketRequest(BaseModel):
    model_config = {"extra": "allow"}
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
    attachments: int | None = 0
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
        # Consolidate images_count vs attachments
        if not ticket_dict.get("images_count") and ticket_dict.get("attachments"):
            ticket_dict["images_count"] = ticket_dict["attachments"]
        result = await pipeline.triage_ticket_async(ticket_dict)
        # УРОВЕНЬ 3: Параноидальный Пост-Чекер перед отдачей финального JSON пользователю
        result["draft_reply"] = sanitize_draft(
            result["draft_reply"], rule_validator.get_valid_rules()
        )
        return result
    except Exception as exc:
        logger.error(f"Unexpected error in triage: {exc}", exc_info=True)
        # Resilient fallback response guaranteeing compliance with the contract
        lang = ticket.lang or ticket.server_lang or "ru"
        draft_lang = lang if lang in ("ru", "kk", "uz", "en") else "ru"
        has_ev = bool((ticket.images_count and ticket.images_count > 0) or (ticket.attachments and ticket.attachments > 0))
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
                has_evidence=has_ev,
                server=ticket.region or ticket.server_lang,
            ),
            draft_reply=DraftReply(
                lang=draft_lang,
                text="Здравствуйте! Ваше обращение принято к рассмотрению. Ожидайте ответа администратора.",
                cited=[],
            ),
            needs_human=True,
            confidence=0.50,
            reasons=[f"Обращение направлено оператору для ручной проверки: {exc!s}"],
        )


# =============================================================================
# 🔌 B2B CRM Webhooks & Автономный авто-ответчик («Via автоматизация»)
# =============================================================================

@app.post("/webhook/crm/ticket")
async def webhook_crm_ticket(payload: dict[str, Any]):
    """
    Универсальный B2B Вебхук для приема тикетов из любой CRM-системы
    (amoCRM, Bitrix24, Helpdesk, Webhook).
    - Автоматически адаптирует структуру запроса
    - Выполняет интеллектуальный триаж и генерацию черновика
    - Если разрешено политикой безопасности -> автономно отправляет ответ по callback_url
    - Если требуется оператор -> эскалирует и возвращает готовый черновик
    """
    try:
        adapted_ticket = crm_manager.adapt_inbound_ticket("generic", payload)
        triage_res = await pipeline.triage_ticket_async(adapted_ticket)
        triage_res["draft_reply"] = sanitize_draft(
            triage_res["draft_reply"], rule_validator.get_valid_rules()
        )
        dispatch_res = await crm_manager.process_and_dispatch(adapted_ticket, triage_res)
        return dispatch_res
    except Exception as e:
        logger.error(f"CRM Webhook error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"CRM processing error: {e!s}"},
        )


@app.post("/webhook/telegram")
async def webhook_telegram(update: dict[str, Any]):
    """
    Вебхук для прямого подключения Telegram Support Bot:
    - Принимает сообщение игрока / клиента из Telegram
    - Триажирует и генерирует регламентный ответ
    - При высоком доверии -> сразу отправляет ответ в чат Telegram
    - При эскалации -> отправляет уведомление в закрытый канал операторов
    """
    try:
        adapted_ticket = crm_manager.adapt_inbound_ticket("telegram", update)
        if not adapted_ticket:
            return {"status": "ignored", "reason": "No message in update"}

        triage_res = await pipeline.triage_ticket_async(adapted_ticket)
        triage_res["draft_reply"] = sanitize_draft(
            triage_res["draft_reply"], rule_validator.get_valid_rules()
        )
        dispatch_res = await crm_manager.process_and_dispatch(adapted_ticket, triage_res)
        return dispatch_res
    except Exception as e:
        logger.error(f"Telegram Webhook error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/webhook/zendesk")
async def webhook_zendesk(payload: dict[str, Any]):
    """
    Вебхук интеграции с Zendesk Support:
    - Принимает событие создания/обновления тикета в Zendesk
    - При авто-ответе -> публикует публичный комментарий и переводит тикет в 'solved'
    - При эскалации -> публикует закрытую внутреннюю заметку (Internal Note) для оператора
    """
    try:
        adapted_ticket = crm_manager.adapt_inbound_ticket("zendesk", payload)
        triage_res = await pipeline.triage_ticket_async(adapted_ticket)
        triage_res["draft_reply"] = sanitize_draft(
            triage_res["draft_reply"], rule_validator.get_valid_rules()
        )
        dispatch_res = await crm_manager.process_and_dispatch(adapted_ticket, triage_res)
        return dispatch_res
    except Exception as e:
        logger.error(f"Zendesk Webhook error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/crm/metrics")
def get_crm_metrics():
    """Возвращает агрегированные B2B метрики автоматизации и Deflection Rate."""
    return crm_manager.get_audit_metrics()


@app.get("/crm/config")
def get_crm_config():
    """Возвращает текущую конфигурацию B2B CRM и авто-ответчика."""
    return crm_manager.config


@app.post("/crm/config")
def update_crm_config(config_update: dict[str, Any]):
    """Обновляет настройки автономного авто-ответчика и интеграций."""
    try:
        crm_manager.save_config(config_update)
        return {"status": "success", "config": crm_manager.config}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# =============================================================================
# 📖 Динамическое управление базой знаний и правилами компании
# =============================================================================

@app.post("/rules/upload")
async def upload_rules(request: Request):
    """
    Загрузка и динамическое обновление базы знаний компании:
    - Принимает JSON со структурой правил или произвольный текст/Markdown
    - Поддерживает application/json, multipart/form-data и text/plain
    - Мгновенно переиндексирует RAG и классификатор без остановки сервиса
    """
    try:
        content_type = request.headers.get("content-type", "")
        content_to_parse = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            file = form.get("file")
            if file and hasattr(file, "read"):
                raw_bytes = await file.read()
                content_to_parse = raw_bytes.decode("utf-8", errors="replace")
            else:
                text_field = form.get("text") or form.get("rules")
                if text_field:
                    content_to_parse = str(text_field)
        elif "application/json" in content_type:
            content_to_parse = await request.json()
        else:
            raw_body = await request.body()
            content_to_parse = raw_body.decode("utf-8", errors="replace")

        if not content_to_parse:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "No rules content or file provided"},
            )

        parsed = parse_rules_content(content_to_parse)
        saved_path = save_active_rules(parsed)
        pipeline.reload_rules(saved_path)
        rule_validator.load_from_data(parsed)

        return {
            "status": "success",
            "message": "База знаний успешно обновлена и переиндексирована на лету",
            "name": parsed.get("name"),
            "rules_count": len(rule_validator),
            "categories": pipeline.classifier.categories,
            "rules_path": saved_path,
        }
    except Exception as e:
        logger.error(f"Failed to upload rules: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/rules/active")
def get_active_rules():
    """Возвращает текущую активную базу знаний и список категорий."""
    return {
        "rules_count": len(rule_validator),
        "valid_refs": sorted(list(rule_validator.get_valid_rules())),
        "categories": pipeline.classifier.categories,
        "points": rule_validator.get_points_list(),
    }


@app.post("/rules/reset")
def reset_rules():
    """Сбрасывает базу знаний к базовому корпоративному регламенту."""
    try:
        if os.path.exists(DEFAULT_RULES_PATH):
            with open(DEFAULT_RULES_PATH, "r", encoding="utf-8") as f:
                default_data = json.load(f)
            save_active_rules(default_data)
            pipeline.reload_rules(default_data)
            rule_validator.load_from_data(default_data)
            return {
                "status": "success",
                "message": "База знаний сброшена к базовому корпоративному регламенту",
                "rules_count": len(rule_validator),
                "categories": pipeline.classifier.categories,
            }
        else:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Default rules file not found"},
            )
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
