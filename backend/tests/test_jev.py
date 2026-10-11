"""Jev client tests. The official SDK uses `httpx2`, so requests are mocked with `httpx2.MockTransport`
(respx only intercepts `httpx`); see DECISIONS.md."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.errors import DocumentError, ErrorCode
from app.services.classification.categories import CATEGORY_KEYS, CRITERIA, INSTRUCTIONS
from app.services.classification.jev import JevClassifier
from tests.conftest import SENTINEL_JEV_KEY, uniform_probabilities

BASE_URL = "https://api.typesafe.ai"


def ok_body(
    choice: str = "invoice_from_supplier",
    probabilities: dict[str, float] | None = None,
    confidence: float = 0.91,
    model: str = "jev-1.13.0",
) -> dict[str, Any]:
    return {
        "model": model,
        "answers": {
            "document_type": {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities if probabilities is not None else uniform_probabilities(choice, 0.91),
                "confidence": confidence,
            }
        },
        "usage": {"input_tokens": 1842, "output_tokens": 34},
    }


class Recorder:
    def __init__(self, responses: list[httpx2.Response | Exception]) -> None:
        self.responses = responses
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def make_jev() -> Callable[[list[httpx2.Response | Exception]], tuple[JevClassifier, Recorder]]:
    def _make(responses: list[httpx2.Response | Exception]) -> tuple[JevClassifier, Recorder]:
        rec = Recorder(responses)
        jev = JevClassifier(
            api_key=SENTINEL_JEV_KEY, base_url=BASE_URL, model="jev-latest", transport=httpx2.MockTransport(rec)
        )
        return jev, rec

    return _make


async def test_builds_exact_request_body(make_jev: Any) -> None:
    jev, rec = make_jev([httpx2.Response(200, json=ok_body())])
    await jev.classify("TAX INVOICE ...", "inv_0412.pdf", 2)
    req = rec.requests[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.typesafe.ai/v1/systemone"
    assert req.headers["authorization"] == f"Bearer {SENTINEL_JEV_KEY}"
    body = json.loads(req.content)
    assert body == {
        "model": "jev-latest",
        "state": {"document_text": "TAX INVOICE ...", "filename": "inv_0412.pdf", "page_count": 2},
        "questions": {"document_type": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}},
    }
    assert list(body["questions"]["document_type"]["criteria"]) == list(CATEGORY_KEYS)
    assert len(CATEGORY_KEYS) == 11


async def test_parses_response_and_records_model(make_jev: Any) -> None:
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(model="jev-1.13.0"))])
    out = await jev.classify("text", "a.pdf", 1)
    assert out.document_type == "invoice_from_supplier"
    assert out.document_type_label == "Invoice from Supplier"
    assert out.confidence == 0.91
    assert set(out.probabilities) == set(CATEGORY_KEYS)
    assert out.model == "jev-1.13.0"  # versioned id from the response, not the requested alias
    assert out.warnings == []


async def test_rejects_unknown_choice(make_jev: Any) -> None:
    probs = uniform_probabilities("receipt")
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(choice="memo", probabilities=probs))])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_INVALID_RESPONSE


async def test_rejects_probabilities_not_summing_to_one(make_jev: Any) -> None:
    probs = {k: 0.5 for k in CATEGORY_KEYS}
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(probabilities=probs))])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_INVALID_RESPONSE


async def test_accepts_sum_within_tolerance(make_jev: Any) -> None:
    probs = uniform_probabilities("receipt", 0.9)
    probs["receipt"] += 0.009
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(choice="receipt", probabilities=probs))])
    assert (await jev.classify("text", "a.pdf", 1)).document_type == "receipt"


async def test_rejects_wrong_key_set(make_jev: Any) -> None:
    probs = uniform_probabilities("receipt")
    probs.pop("bill")
    probs["memo"] = 0.01
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(choice="receipt", probabilities=probs))])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_INVALID_RESPONSE


async def test_rejects_confidence_out_of_range(make_jev: Any) -> None:
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(confidence=1.5))])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_INVALID_RESPONSE


async def test_malformed_response_is_invalid(make_jev: Any) -> None:
    jev, _ = make_jev([httpx2.Response(200, json={"model": "jev-1", "answers": {}, "usage": {}})])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_INVALID_RESPONSE


async def test_choice_not_argmax_adds_warning(make_jev: Any) -> None:
    probs = uniform_probabilities("receipt", 0.6)
    jev, _ = make_jev([httpx2.Response(200, json=ok_body(choice="bill", probabilities=probs))])
    out = await jev.classify("text", "a.pdf", 1)
    assert out.document_type == "bill"  # trust choice
    assert out.warnings == ["choice_not_argmax"]


@pytest.mark.parametrize("status", [429, 529])
async def test_retries_with_backoff_then_succeeds(make_jev: Any, no_sleep: list[float], status: int) -> None:
    jev, rec = make_jev([httpx2.Response(status, json={"error": "busy"})] * 3 + [httpx2.Response(200, json=ok_body())])
    out = await jev.classify("text", "a.pdf", 1)
    assert out.document_type == "invoice_from_supplier"
    assert len(rec.requests) == 4
    for expected, actual in zip([1, 2, 4], no_sleep, strict=True):
        assert expected <= actual <= expected + 0.25


async def test_retry_exhausted_is_unavailable(make_jev: Any) -> None:
    jev, rec = make_jev([httpx2.Response(529, json={"error": "overloaded"})])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == ErrorCode.JEV_UNAVAILABLE
    assert len(rec.requests) == 4


async def test_honours_retry_after(make_jev: Any, no_sleep: list[float]) -> None:
    limited = httpx2.Response(429, headers={"retry-after": "9"}, json={"error": "slow"})
    jev, _ = make_jev([limited, httpx2.Response(200, json=ok_body())])
    await jev.classify("text", "a.pdf", 1)
    assert no_sleep == [9.0]


async def test_timeout_retried(make_jev: Any) -> None:
    jev, rec = make_jev([httpx2.ReadTimeout("slow"), httpx2.Response(200, json=ok_body())])
    await jev.classify("text", "a.pdf", 1)
    assert len(rec.requests) == 2


@pytest.mark.parametrize(("status", "code"), [(401, ErrorCode.JEV_AUTH_ERROR), (422, ErrorCode.JEV_BAD_REQUEST)])
async def test_no_retry_on_401_422(make_jev: Any, status: int, code: ErrorCode) -> None:
    jev, rec = make_jev([httpx2.Response(status, json={"error": "nope"})])
    with pytest.raises(DocumentError) as err:
        await jev.classify("text", "a.pdf", 1)
    assert err.value.code == code
    assert len(rec.requests) == 1
