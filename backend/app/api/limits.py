"""Request body-size limit (UPLOAD_TOO_LARGE) and per-IP submission rate limit (PRD 10.0)."""

import json
import time
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import ErrorCode, message_for

UPLOAD_BODY_LIMIT_BYTES = 220 * 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects bodies over the limit with 413 UPLOAD_TOO_LARGE — via Content-Length up front, or while streaming."""

    def __init__(self, app: ASGIApp, limit_bytes: int | None = None) -> None:
        self.app = app
        self._limit_bytes = limit_bytes

    @property
    def limit_bytes(self) -> int:
        # Resolved per request so the module constant can be lowered in tests.
        return self._limit_bytes if self._limit_bytes is not None else UPLOAD_BODY_LIMIT_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.limit_bytes:
                        await self._reject(send)
                        return
                except ValueError:
                    pass

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        code = ErrorCode.UPLOAD_TOO_LARGE
        body = json.dumps({"error_code": code.value, "error_message": message_for(code)}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """Sliding-window limiter: at most `limit` accepted submissions per client IP per `window_s`."""

    def __init__(self, limit: int = 30, window_s: float = 3600.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        return hits

    def allowed(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) < self.limit

    def record(self, key: str) -> None:
        self._hits[key].append(time.monotonic())
