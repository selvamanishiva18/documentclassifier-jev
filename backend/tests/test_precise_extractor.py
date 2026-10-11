import base64
import json
from typing import Any

import httpx
import pytest
import respx

from app.errors import DocumentError, ErrorCode
from app.services.extraction.precise import (
    CORRECTIVE_PROMPT,
    HAIKU_SYSTEM_PROMPT,
    PreciseExtractor,
    parse_payload,
    strip_code_fences,
    truncate_pdf,
)
from app.services.validation import count_pdf_pages
from tests.conftest import SENTINEL_ANTHROPIC_KEY, fixture_bytes

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"


def message(text: str) -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


GOOD = json.dumps(
    {
        "raw_text": "TAX INVOICE\nAcme Supplies Pty Ltd",
        "fields": {
            "document_number": "INV-1",
            "total_amount": "1,298.00",
            "vendor_abn": "12 345",  # non-canonical: dropped
            "subtotal": "",  # empty: dropped
            "tax_amount": 118.0,  # non-string: dropped
        },
    }
)


@pytest.fixture
def extractor() -> PreciseExtractor:
    return PreciseExtractor(api_key=SENTINEL_ANTHROPIC_KEY, model=MODEL)


def _body(route: respx.Route, call: int = 0) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(route.calls[call].request.content)
    return body


@respx.mock
async def test_parses_valid_json_and_filters_fields(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=message(GOOD)))
    result = await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert result.raw_text.startswith("TAX INVOICE")
    assert result.fields == {"document_number": "INV-1", "total_amount": "1,298.00"}
    assert result.page_count == 1
    body = _body(route)
    assert body["model"] == MODEL
    assert body["temperature"] == 0
    assert body["max_tokens"] == 4096
    assert body["system"] == HAIKU_SYSTEM_PROMPT
    block = body["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"
    assert route.calls[0].request.headers["x-api-key"] == SENTINEL_ANTHROPIC_KEY


@respx.mock
async def test_pdf_sent_as_document_block(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=message(GOOD)))
    result = await extractor.extract(fixture_bytes("invoice.pdf"), "application/pdf", "i.pdf", 20)
    block = _body(route)["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert block["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": base64.b64encode(fixture_bytes("invoice.pdf")).decode(),
    }
    assert result.page_count == 2


@respx.mock
async def test_pdf_truncated_before_sending(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=message(GOOD)))
    result = await extractor.extract(fixture_bytes("long_21_pages.pdf"), "application/pdf", "l.pdf", 20)
    sent = base64.b64decode(_body(route)["messages"][0]["content"][0]["source"]["data"])
    assert count_pdf_pages(sent) == 20
    assert result.page_count == 20


@respx.mock
async def test_strips_code_fences(extractor: PreciseExtractor) -> None:
    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=message(f"```json\n{GOOD}\n```")))
    result = await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert result.fields is not None and result.fields["document_number"] == "INV-1"


@respx.mock
async def test_retries_once_on_invalid_json_then_succeeds(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(
        side_effect=[httpx.Response(200, json=message("not json")), httpx.Response(200, json=message(GOOD))]
    )
    result = await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert result.raw_text
    assert route.call_count == 2
    second_content = _body(route, 1)["messages"][0]["content"]
    assert second_content[-1] == {"type": "text", "text": CORRECTIVE_PROMPT}


@respx.mock
async def test_invalid_json_twice_is_bad_output(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=message('{"raw_text": ""}')))
    with pytest.raises(DocumentError) as err:
        await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert err.value.code == ErrorCode.HAIKU_BAD_OUTPUT
    assert route.call_count == 2


@respx.mock
async def test_429_retried_then_unavailable(extractor: PreciseExtractor, no_sleep: list[float]) -> None:
    route = respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "x"}})
    )
    with pytest.raises(DocumentError) as err:
        await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert err.value.code == ErrorCode.HAIKU_UNAVAILABLE
    assert route.call_count == 4
    assert len(no_sleep) == 3
    for expected, actual in zip([1, 2, 4], no_sleep, strict=True):
        assert expected <= actual <= expected + 0.25


@respx.mock
async def test_529_then_success(extractor: PreciseExtractor) -> None:
    overloaded = httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}})
    route = respx.post(MESSAGES_URL).mock(side_effect=[overloaded, httpx.Response(200, json=message(GOOD))])
    result = await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert result.raw_text
    assert route.call_count == 2


@respx.mock
async def test_retry_after_header_honoured(extractor: PreciseExtractor, no_sleep: list[float]) -> None:
    limited = httpx.Response(
        429, headers={"retry-after": "7"}, json={"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}
    )
    respx.post(MESSAGES_URL).mock(side_effect=[limited, httpx.Response(200, json=message(GOOD))])
    await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert no_sleep == [7.0]


@respx.mock
async def test_401_is_auth_error_without_retry(extractor: PreciseExtractor) -> None:
    unauthorized = {"type": "error", "error": {"type": "authentication_error", "message": "x"}}
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(401, json=unauthorized))
    with pytest.raises(DocumentError) as err:
        await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert err.value.code == ErrorCode.HAIKU_AUTH_ERROR
    assert route.call_count == 1


@respx.mock
async def test_timeout_retried_then_unavailable(extractor: PreciseExtractor) -> None:
    route = respx.post(MESSAGES_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DocumentError) as err:
        await extractor.extract(fixture_bytes("receipt.jpg"), "image/jpeg", "r.jpg", 20)
    assert err.value.code == ErrorCode.HAIKU_UNAVAILABLE
    assert route.call_count == 4


def test_parse_payload_shapes() -> None:
    assert parse_payload('{"raw_text": "abc"}') == ("abc", {})
    assert parse_payload('{"raw_text": "abc", "fields": null}') == ("abc", {})
    for bad in ("[]", '{"raw_text": 5}', '{"raw_text": "  "}', '{"raw_text": "a", "fields": []}', "nope"):
        with pytest.raises(Exception, match=r".+"):
            parse_payload(bad)


def test_strip_code_fences() -> None:
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('  {"a": 1} ') == '{"a": 1}'


def test_truncate_pdf_noop_under_cap() -> None:
    data = fixture_bytes("invoice.pdf")
    assert truncate_pdf(data, 20) == (data, 2)
