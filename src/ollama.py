import base64
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

PROMPTS_DIR = Path(__file__).parent / "prompts"
ANALYSIS_PROMPT_PATH = PROMPTS_DIR / "analysis.tmpl"


class ExtractedDocument(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("content", mode="before")
    @classmethod
    def stringify_content(cls, content: Any) -> str:
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        return json.dumps(content, ensure_ascii=False, indent=2)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, tags: Any) -> list[str]:
        if not isinstance(tags, list):
            return []

        normalized: list[str] = []
        seen: set[str] = set()

        for tag in tags:
            tag_name = extract_tag_name(tag)

            if tag_name is None:
                continue

            clean = " ".join(tag_name.strip().split())

            if not clean or len(clean) > 64:
                continue

            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)

        return normalized[:10]


def extract_tag_name(tag: Any) -> str | None:
    if isinstance(tag, str):
        return tag

    if not isinstance(tag, dict):
        return None

    for key in ("name", "tag-name", "tag_name", "tag", "label"):
        value = tag.get(key)

        if isinstance(value, str):
            return value

    return None


class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=180)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def generate(
        self,
        prompt: str,
        image_bytes_list: Sequence[bytes] | None = None,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        if image_bytes_list:
            request["images"] = [
                base64.b64encode(image_bytes).decode("utf-8")
                for image_bytes in image_bytes_list
            ]

        response = await self.client.post(
            f"{self.base_url}/api/generate",
            json=request,
        )
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        return data["response"]


def build_analysis_prompt(
    *,
    filename: str,
    existing_content: str | None,
    available_tags: Sequence[Mapping[str, Any]],
) -> str:
    tag_names = [str(tag["name"]) for tag in available_tags if tag.get("name")]
    tags = "\n".join(f"- {name}" for name in tag_names) or "- none"
    content = existing_content or ""

    return (
        Template(ANALYSIS_PROMPT_PATH.read_text())
        .substitute(
            filename=filename,
            existing_content=content[:12000],
            available_tags=tags,
        )
        .strip()
    )


def parse_extracted_document(
    raw_response: str, fallback_title: str
) -> ExtractedDocument:
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError("Ollama did not return valid JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("Ollama JSON response must be an object")

    data.setdefault("title", fallback_title)
    data.setdefault("content", "")
    data.setdefault("tags", [])

    try:
        return ExtractedDocument.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            "Ollama JSON response did not match the expected schema"
        ) from exc


async def analyze_with_ollama(
    *,
    client: OllamaClient,
    file_bytes: bytes,
    filename: str,
    existing_content: str | None,
    available_tags: Sequence[Mapping[str, Any]],
    vision_images: Sequence[bytes],
) -> ExtractedDocument:
    prompt = build_analysis_prompt(
        filename=filename,
        existing_content=existing_content,
        available_tags=available_tags,
    )
    raw_response = await client.generate(
        prompt=prompt,
        image_bytes_list=vision_images,
    )

    return parse_extracted_document(raw_response, fallback_title=filename)
