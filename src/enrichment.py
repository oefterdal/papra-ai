import logging

import httpx

from config import Settings
from ollama import OllamaClient, analyze_with_ollama
from papra import PapraClient
from pdfs import render_pdf_pages
from webhooks import PapraWebhookEvent

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}


async def handle_document_created(
    event: PapraWebhookEvent,
    *,
    papra: PapraClient,
    ollama: OllamaClient,
    settings: Settings,
) -> None:
    org_id, document_id = event.require_document_ids()
    document = await papra.get_document(org_id, document_id)
    file_bytes = await papra.get_document_file(org_id, document_id)
    available_tags = await papra.list_tags(org_id)
    vision_images = document_vision_images(
        file_bytes=file_bytes,
        filename=document["name"],
        settings=settings,
    )

    try:
        extracted = await analyze_with_ollama(
            client=ollama,
            file_bytes=file_bytes,
            filename=document["name"],
            existing_content=document.get("content"),
            available_tags=available_tags,
            vision_images=vision_images,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Ollama request failed: %s. Check OLLAMA_BASE_URL=%s and OLLAMA_MODEL=%s",
            exc,
            settings.ollama_base_url,
            settings.ollama_model,
        )
        raise RuntimeError(
            "Ollama request failed. Check OLLAMA_BASE_URL and model availability."
        ) from exc

    await papra.update_document(
        org_id=org_id,
        document_id=document_id,
        name=extracted.title,
        content=extracted.content,
    )

    existing_tag_names = {
        tag["name"].casefold() for tag in document.get("tags", []) if "name" in tag
    }
    tags_by_name = {
        tag["name"].casefold(): tag for tag in available_tags if "name" in tag
    }

    for tag_name in extracted.tags:
        if tag_name.casefold() in existing_tag_names:
            continue

        tag = tags_by_name.get(tag_name.casefold())

        if tag is None:
            tag = await papra.create_tag(
                org_id,
                tag_name,
                color=settings.papra_ai_tag_color,
            )
            tags_by_name[tag_name.casefold()] = tag

        await papra.add_tag(org_id, document_id, tag["id"])
        existing_tag_names.add(tag_name.casefold())


def is_image_filename(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(extension) for extension in IMAGE_EXTENSIONS)


def is_pdf_filename(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(extension) for extension in PDF_EXTENSIONS)


def document_vision_images(
    *,
    file_bytes: bytes,
    filename: str,
    settings: Settings,
) -> list[bytes]:
    if is_image_filename(filename):
        return [file_bytes]

    if is_pdf_filename(filename):
        return render_pdf_pages(
            file_bytes,
            max_pages=settings.pdf_max_pages,
            dpi=settings.pdf_render_dpi,
        )

    return []
