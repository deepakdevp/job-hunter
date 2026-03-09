"""Notion API wrapper — thin layer over notion-client."""

from __future__ import annotations

from notion_client import Client


class NotionClient:
    def __init__(self, token: str):
        self._client = Client(auth=token)

    # ---- Pages ----

    def create_page(self, database_id: str, properties: dict) -> dict:
        return self._client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
        )

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._client.pages.update(page_id=page_id, properties=properties)

    def get_page(self, page_id: str) -> dict:
        return self._client.pages.retrieve(page_id=page_id)

    def query_database(self, database_id: str, filter: dict | None = None, sorts: list | None = None) -> list[dict]:
        kwargs: dict = {"database_id": database_id}
        if filter:
            kwargs["filter"] = filter
        if sorts:
            kwargs["sorts"] = sorts

        results = []
        has_more = True
        cursor = None
        while has_more:
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self._client.databases.query(**kwargs)
            results.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            cursor = response.get("next_cursor")
        return results

    # ---- Databases ----

    def create_database(self, parent_page_id: str, title: str, properties: dict) -> dict:
        return self._client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": title}}],
            properties=properties,
        )

    def get_database(self, database_id: str) -> dict:
        return self._client.databases.retrieve(database_id=database_id)

    # ---- Helpers ----

    def append_block(self, page_id: str, blocks: list[dict]) -> dict:
        return self._client.blocks.children.append(block_id=page_id, children=blocks)
