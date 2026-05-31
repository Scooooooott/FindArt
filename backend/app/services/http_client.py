from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class JsonHttpClient(Protocol):
    async def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        ...


class UrllibJsonHttpClient:
    def __init__(self, timeout_seconds: float = 8.0, user_agent: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or os.getenv(
            "FINDART_USER_AGENT",
            "MasterpieceTracingApp/0.1 (https://example.invalid/findart; contact@example.invalid)",
        )

    async def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._get_json_sync,
            url,
            params or {},
            headers or {},
        )

    def _get_json_sync(
        self,
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        request_url = _append_params(url, params)
        request = Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                **headers,
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object response.")
        return data


def _append_params(url: str, params: Mapping[str, Any]) -> str:
    clean_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    if not clean_params:
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(clean_params, doseq=True)}"
