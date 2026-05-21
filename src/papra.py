from typing import Any

import httpx


class PapraClient:
    def __init__(self, base_url: str, api_token: str):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_token}",
            },
            timeout=60,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get_document(
        self,
        org_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        response = await self.client.get(
            f"/api/organizations/{org_id}/documents/{document_id}"
        )

        response.raise_for_status()

        return response.json()["document"]

    async def get_document_file(
        self,
        org_id: str,
        document_id: str,
    ) -> bytes:
        response = await self.client.get(
            f"/api/organizations/{org_id}/documents/{document_id}/file"
        )

        response.raise_for_status()

        return response.content

    async def update_document(
        self,
        org_id: str,
        document_id: str,
        *,
        name: str,
        content: str,
    ) -> None:
        response = await self.client.patch(
            f"/api/organizations/{org_id}/documents/{document_id}",
            json={
                "name": name,
                "content": content,
            },
        )

        response.raise_for_status()

    async def list_tags(self, org_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(f"/api/organizations/{org_id}/tags")
        response.raise_for_status()

        return response.json()["tags"]

    async def create_tag(
        self,
        org_id: str,
        name: str,
        *,
        color: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "color": color,
        }

        if description:
            payload["description"] = description

        response = await self.client.post(
            f"/api/organizations/{org_id}/tags",
            json=payload,
        )
        response.raise_for_status()

        return response.json()["tag"]

    async def get_or_create_tag(
        self,
        org_id: str,
        name: str,
        *,
        color: str = "#5B8DEF",
    ) -> dict[str, Any]:
        normalized_name = name.casefold()

        for tag in await self.list_tags(org_id):
            if tag["name"].casefold() == normalized_name:
                return tag

        return await self.create_tag(org_id, name, color=color)

    async def add_tag(
        self,
        org_id: str,
        document_id: str,
        tag_id: str,
    ) -> None:
        response = await self.client.post(
            f"/api/organizations/{org_id}/documents/{document_id}/tags",
            json={"tagId": tag_id},
        )
        response.raise_for_status()
