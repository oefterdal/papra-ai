import base64
import hashlib
import hmac
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pymupdf
from fastapi import BackgroundTasks, HTTPException, Request

os.environ.setdefault("PAPRA_API_TOKEN", "test-api-token")
os.environ.setdefault("PAPRA_WEBHOOK_SECRET", "test-webhook-secret")

import main
import webhooks
from config import Settings
from enrichment import (
    document_vision_images,
    handle_document_created,
    is_image_filename,
    is_pdf_filename,
)
from main import enrich_document_in_background, health, papra_webhook
from webhooks import (
    PapraWebhookEvent,
    accept_webhook_id,
    verify_papra_webhook_signature,
)

WEBHOOK_SECRET_BYTES = b"test-webhook-secret"
WEBHOOK_SECRET = f"whsec_{base64.b64encode(WEBHOOK_SECRET_BYTES).decode()}"
WEBHOOK_ID = "msg_1"
WEBHOOK_TIMESTAMP = "1754678128"


def make_signed_webhook_request(payload: dict[str, object]) -> tuple[Request, bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signed_content = b".".join([WEBHOOK_ID.encode(), WEBHOOK_TIMESTAMP.encode(), body])
    signature = base64.b64encode(
        hmac.digest(WEBHOOK_SECRET_BYTES, signed_content, hashlib.sha256)
    ).decode()
    headers = [
        (b"webhook-id", WEBHOOK_ID.encode()),
        (b"webhook-timestamp", WEBHOOK_TIMESTAMP.encode()),
        (b"webhook-signature", f"v1,{signature}".encode()),
    ]

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "headers": headers, "app": main.app}, receive), body


class MainHelpersTest(unittest.TestCase):
    def test_standard_webhook_payload_populates_ids(self) -> None:
        event = PapraWebhookEvent.model_validate(
            {
                "type": "document:created",
                "data": {
                    "organizationId": "org_1",
                    "documentId": "doc_1",
                },
            }
        )

        self.assertEqual(event.event_name, "document:created")
        self.assertEqual(event.organization_id, "org_1")
        self.assertEqual(event.document_id, "doc_1")

    def test_is_image_filename(self) -> None:
        self.assertTrue(is_image_filename("receipt.PNG"))
        self.assertFalse(is_image_filename("invoice.pdf"))

    def test_is_pdf_filename(self) -> None:
        self.assertTrue(is_pdf_filename("invoice.PDF"))
        self.assertFalse(is_pdf_filename("receipt.png"))

    def test_document_vision_images_renders_limited_pdf_pages(self) -> None:
        document = pymupdf.open()
        for page_number in range(3):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {page_number + 1}")
        pdf_bytes = document.tobytes()
        document.close()

        images = document_vision_images(
            file_bytes=pdf_bytes,
            filename="invoice.pdf",
            settings=Settings(
                papra_api_token="token",
                papra_webhook_secret="secret",
                pdf_max_pages=2,
                pdf_render_dpi=72,
                _env_file=None,
            ),
        )

        self.assertEqual(len(images), 2)
        self.assertTrue(all(image.startswith(b"\x89PNG") for image in images))


class WebhookTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        webhooks.accepted_webhook_ids.clear()
        main.app.state.settings = SimpleNamespace(
            papra_webhook_secret=WEBHOOK_SECRET,
        )
        main.app.state.papra = object()
        main.app.state.ollama = object()

    async def test_health_returns_ok(self) -> None:
        self.assertEqual(await health(), {"ok": True})

    async def test_document_created_webhook_schedules_background_enrichment(
        self,
    ) -> None:
        request, _ = make_signed_webhook_request(
            {
                "type": "document:created",
                "organizationId": "org_1",
                "documentId": "doc_1",
            }
        )
        background_tasks = BackgroundTasks()

        with (
            patch.object(
                webhooks.time, "time", Mock(return_value=int(WEBHOOK_TIMESTAMP))
            ),
        ):
            response = await papra_webhook(request, background_tasks)

        self.assertEqual(response, {"ok": True, "accepted": "doc_1"})
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertIs(background_tasks.tasks[0].func, enrich_document_in_background)
        event = background_tasks.tasks[0].args[0]
        self.assertEqual(event.organization_id, "org_1")
        self.assertEqual(event.document_id, "doc_1")

    async def test_document_created_webhook_deduplicates_webhook_id(self) -> None:
        request, _ = make_signed_webhook_request(
            {
                "type": "document:created",
                "organizationId": "org_1",
                "documentId": "doc_1",
            }
        )
        retry, _ = make_signed_webhook_request(
            {
                "type": "document:created",
                "organizationId": "org_1",
                "documentId": "doc_1",
            }
        )

        with (
            patch.object(
                webhooks.time, "time", Mock(return_value=int(WEBHOOK_TIMESTAMP))
            ),
        ):
            accepted_tasks = BackgroundTasks()
            duplicate_tasks = BackgroundTasks()
            accepted = await papra_webhook(request, accepted_tasks)
            duplicate = await papra_webhook(retry, duplicate_tasks)

        self.assertEqual(accepted, {"ok": True, "accepted": "doc_1"})
        self.assertEqual(duplicate, {"ok": True, "duplicate": WEBHOOK_ID})
        self.assertEqual(len(accepted_tasks.tasks), 1)
        self.assertEqual(len(duplicate_tasks.tasks), 0)

    async def test_webhook_rejects_invalid_signature(self) -> None:
        request, _ = make_signed_webhook_request(
            {
                "type": "document:created",
                "organizationId": "org_1",
                "documentId": "doc_1",
            }
        )
        request.scope["headers"][-1] = (b"webhook-signature", b"v1,invalid")

        with (
            patch.object(
                webhooks.time, "time", Mock(return_value=int(WEBHOOK_TIMESTAMP))
            ),
        ):
            with self.assertRaises(HTTPException) as exc:
                await papra_webhook(request, BackgroundTasks())

        self.assertEqual(exc.exception.status_code, 401)

    def test_webhook_rejects_stale_timestamp(self) -> None:
        _, body = make_signed_webhook_request({"type": "document:created"})

        with self.assertRaises(HTTPException) as exc:
            verify_papra_webhook_signature(
                body=body,
                headers={
                    "webhook-id": WEBHOOK_ID,
                    "webhook-timestamp": WEBHOOK_TIMESTAMP,
                    "webhook-signature": "v1,unused",
                },
                secret=WEBHOOK_SECRET,
                now=int(WEBHOOK_TIMESTAMP) + 301,
            )

        self.assertEqual(exc.exception.status_code, 401)

    def test_accept_webhook_id_expires_old_ids(self) -> None:
        self.assertTrue(accept_webhook_id("msg_1", now=1_000))
        self.assertFalse(accept_webhook_id("msg_1", now=1_299))
        self.assertTrue(accept_webhook_id("msg_1", now=1_300))

    async def test_background_enrichment_logs_failures(self) -> None:
        event = PapraWebhookEvent(
            type="document:created",
            organizationId="org_1",
            documentId="doc_1",
        )

        with (
            patch.object(
                main,
                "handle_document_created",
                AsyncMock(side_effect=RuntimeError("failed")),
            ),
            patch.object(main.logger, "exception", Mock()) as log_exception,
        ):
            await enrich_document_in_background(
                event,
                object(),
                object(),
                Settings(
                    papra_api_token="token",
                    papra_webhook_secret="secret",
                    _env_file=None,
                ),
            )

        log_exception.assert_called_once()


class FakePapraClient:
    async def get_document(self, org_id: str, document_id: str) -> dict[str, object]:
        return {"name": "receipt.png", "content": ""}

    async def get_document_file(self, org_id: str, document_id: str) -> bytes:
        return b"image"

    async def list_tags(self, org_id: str) -> list[dict[str, object]]:
        return []


async def fail_ollama_analysis(**kwargs: object) -> object:
    request = httpx.Request("POST", "http://ollama:11434/api/generate")
    raise httpx.ConnectError("All connection attempts failed", request=request)


class OllamaFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_handle_document_created_returns_503_when_ollama_unavailable(
        self,
    ) -> None:
        event = PapraWebhookEvent(
            type="document:created",
            organizationId="org_1",
            documentId="doc_1",
        )

        with (
            patch("enrichment.analyze_with_ollama", fail_ollama_analysis),
        ):
            with self.assertRaises(RuntimeError):
                await handle_document_created(
                    event,
                    papra=FakePapraClient(),
                    ollama=object(),
                    settings=Settings(
                        papra_api_token="token",
                        papra_webhook_secret="secret",
                        _env_file=None,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
