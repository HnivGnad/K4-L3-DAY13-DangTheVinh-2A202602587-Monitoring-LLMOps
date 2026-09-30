from __future__ import annotations

import asyncio
import re

import httpx

from app.main import app


def test_generated_request_ids_are_valid_and_unique() -> None:
    async def send_requests() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/health")
            second = await client.get("/health")
            return first, second

    first, second = asyncio.run(send_requests())
    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]

    assert re.fullmatch(r"req-[0-9a-f]{8}", first_id)
    assert re.fullmatch(r"req-[0-9a-f]{8}", second_id)
    assert first_id != second_id
    assert first.headers["x-response-time-ms"].isdigit()


def test_incoming_request_id_is_propagated() -> None:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/health", headers={"x-request-id": "upstream-request-42"}
            )

    response = asyncio.run(send_request())

    assert response.headers["x-request-id"] == "upstream-request-42"
