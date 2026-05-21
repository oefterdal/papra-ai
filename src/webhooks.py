import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60
ACCEPTED_WEBHOOK_IDS_TTL_SECONDS = 5 * 60
accepted_webhook_ids: dict[str, int] = {}


class PapraWebhookEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str | None = None
    event: str | None = None
    organization_id: str | None = Field(default=None, alias="organizationId")
    document_id: str | None = Field(default=None, alias="documentId")
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_standard_webhook_data(self) -> "PapraWebhookEvent":
        if self.organization_id is None:
            self.organization_id = self.data.get("organizationId")

        if self.document_id is None:
            self.document_id = self.data.get("documentId")

        return self

    @property
    def event_name(self) -> str | None:
        return self.type or self.event

    def require_document_ids(self) -> tuple[str, str]:
        if not self.organization_id:
            raise HTTPException(400, "Missing organization_id")
        if not self.document_id:
            raise HTTPException(400, "Missing document_id")

        return self.organization_id, self.document_id


def verify_papra_webhook_signature(
    *,
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    now: int | None = None,
) -> None:
    webhook_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signatures = headers.get("webhook-signature")

    if not webhook_id or not timestamp or not signatures:
        raise HTTPException(401, "Missing Papra webhook signature headers")

    try:
        timestamp_seconds = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "Invalid Papra webhook timestamp") from exc

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp_seconds) > WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(401, "Papra webhook timestamp is outside tolerance")

    signing_secret = decode_webhook_secret(secret)
    signed_content = b".".join(
        [
            webhook_id.encode(),
            timestamp.encode(),
            body,
        ]
    )
    expected_signature = base64.b64encode(
        hmac.digest(signing_secret, signed_content, hashlib.sha256)
    ).decode()

    if not any(
        hmac.compare_digest(expected_signature, signature)
        for version, signature in parse_webhook_signatures(signatures)
        if version == "v1"
    ):
        raise HTTPException(401, "Invalid Papra webhook signature")


def decode_webhook_secret(secret: str) -> bytes:
    if not secret.startswith("whsec_"):
        return secret.encode()

    try:
        return base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except binascii.Error as exc:
        raise HTTPException(500, "Invalid PAPRA_WEBHOOK_SECRET configuration") from exc


def parse_webhook_signatures(signatures: str) -> list[tuple[str, str]]:
    parsed_signatures: list[tuple[str, str]] = []

    for signature in signatures.split():
        version, separator, value = signature.partition(",")

        if separator and value:
            parsed_signatures.append((version, value))

    return parsed_signatures


def accept_webhook_id(webhook_id: str, now: int | None = None) -> bool:
    current_time = int(time.time()) if now is None else now
    earliest_accepted_time = current_time - ACCEPTED_WEBHOOK_IDS_TTL_SECONDS

    expired_ids = [
        accepted_id
        for accepted_id, accepted_time in accepted_webhook_ids.items()
        if accepted_time <= earliest_accepted_time
    ]
    for accepted_id in expired_ids:
        del accepted_webhook_ids[accepted_id]

    if webhook_id in accepted_webhook_ids:
        return False

    accepted_webhook_ids[webhook_id] = current_time
    return True
