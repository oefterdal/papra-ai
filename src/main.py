import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import ValidationError

from config import Settings, get_settings
from enrichment import handle_document_created
from ollama import OllamaClient
from papra import PapraClient
from webhooks import (
    PapraWebhookEvent,
    accept_webhook_id,
    verify_papra_webhook_signature,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.papra = PapraClient(
        base_url=settings.papra_base_url,
        api_token=settings.papra_api_token,
    )
    app.state.ollama = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )

    logger.info(
        "Papra AI started with Papra base URL %s and Ollama model %s",
        settings.papra_base_url,
        settings.ollama_model,
    )

    try:
        yield
    finally:
        await app.state.papra.aclose()
        await app.state.ollama.aclose()
        logger.info("Papra AI stopped")


app = FastAPI(lifespan=lifespan)


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook")
async def papra_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    settings = request.app.state.settings
    body = await request.body()
    verify_papra_webhook_signature(
        body=body,
        headers=request.headers,
        secret=settings.papra_webhook_secret,
    )

    try:
        event = PapraWebhookEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid Papra webhook payload") from exc

    match event.event_name:
        case "document:created" | "document.created":
            event.require_document_ids()

            webhook_id = request.headers["webhook-id"]
            if not accept_webhook_id(webhook_id):
                logger.info("Ignored duplicate Papra webhook_id=%s", webhook_id)
                return {"ok": True, "duplicate": webhook_id}

            background_tasks.add_task(
                enrich_document_in_background,
                event,
                request.app.state.papra,
                request.app.state.ollama,
                settings,
            )
            logger.info(
                "Accepted Papra webhook_id=%s organization_id=%s document_id=%s",
                webhook_id,
                event.organization_id,
                event.document_id,
            )
            return {"ok": True, "accepted": event.document_id}

        case _:
            # Unknown events should usually be acknowledged,
            # otherwise Papra may retry forever.
            return {"ok": True, "ignored": event.event_name}


async def enrich_document_in_background(
    event: PapraWebhookEvent,
    papra: PapraClient,
    ollama: OllamaClient,
    settings: Settings,
) -> None:
    logger.info(
        "Starting document enrichment organization_id=%s document_id=%s",
        event.organization_id,
        event.document_id,
    )
    try:
        await handle_document_created(
            event,
            papra=papra,
            ollama=ollama,
            settings=settings,
        )
    except Exception:
        logger.exception(
            "Document enrichment failed for organization_id=%s document_id=%s",
            event.organization_id,
            event.document_id,
        )
    else:
        logger.info(
            "Finished document enrichment organization_id=%s document_id=%s",
            event.organization_id,
            event.document_id,
        )
