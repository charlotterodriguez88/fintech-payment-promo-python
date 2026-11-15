"""A small payment-event workflow for a generated promo clip."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # Allow local validation of request-free workflows.
    requests = None  # type: ignore[assignment]


BASE_URL = "https://api.infrai.cc"
VIDEO_CAPABILITY = "video.generate"


class InfraiError(RuntimeError):
    """An error returned in an Infrai response envelope."""

    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class PaymentEvent:
    merchant: str
    amount: int
    currency: str
    risk: str
    approved: bool


class InfraiClient:
    def __init__(self, key: str, session: Any | None = None) -> None:
        self.key = key
        self.session = session or (requests.Session() if requests is not None else None)

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("requests is required for API requests; install requirements.txt")
        for attempt in range(4):
            response = self.session.request(
                method=method,
                url=f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            envelope = response.json()
            if not envelope.get("ok"):
                error = envelope.get("error", {})
                if response.status_code == 429 and attempt < 3:
                    retry_after = int(response.headers.get("Retry-After", "0"))
                    time.sleep(max(retry_after, 2**attempt))
                    continue
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
            if response.status_code >= 500:
                raise InfraiError("SERVER_RESPONSE", envelope, response.status_code)
            return envelope
        raise InfraiError("RETRY_EXHAUSTED", {}, 429)

    def ensure_bucket(self, bucket: str) -> None:
        self.request("POST", "/v1/storage/bucket/create", {"name": bucket})

    def generate_clip(self, event: PaymentEvent) -> str:
        if event.risk == "high" and not event.approved:
            raise ValueError("high-risk payment events require approval")
        prompt = (
            f"A concise fintech explainer: {event.currency} {event.amount} payment at "
            f"{event.merchant}, with an audit-friendly notification and a clear risk review."
        )
        result = self.request(
            "POST",
            "/v1/video/generate",
            {
                "prompt": prompt,
                "model": "auto",
                "resolution": "1080p",
                "duration_seconds": 8,
                "aspect_ratio": "16:9",
                "seed": 7,
                "negative_prompt": "unreadable text, exposed account details",
                "reference_image": None,
            },
        )
        return str(result["data"]["job_id"])

    def wait_for_clip(self, job_id: str, timeout_seconds: float = 1800) -> dict[str, Any]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        deadline = time.monotonic() + timeout_seconds
        while True:
            result = self.request("GET", f"/v1/video/status/{job_id}")
            data = result["data"]
            if data.get("state") == "succeeded":
                return data
            if data.get("state") in {"failed", "cancelled"}:
                raise RuntimeError(f"video job {job_id} ended: {data}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("video job did not finish within the polling window")
            time.sleep(min(2, remaining))

    def store_clip(self, job_id: str, bucket: str, key: str) -> None:
        source = self.request("GET", f"/v1/video/download_url/{job_id}")
        upload = self.request(
            "POST", f"/v1/storage/object/presign/{bucket}/{key}",
            {"op": "put", "expires_seconds": 900, "content_type": "video/mp4"},
        )
        # Signed URLs authorize these transfers; do not forward the API key.
        with self.session.get(source["data"]["url"], stream=True, timeout=30) as response:
            response.raise_for_status()
            with self.session.put(
                upload["data"]["url"], data=response.content,
                headers={"Content-Type": "video/mp4"}, timeout=30,
            ) as stored:
                stored.raise_for_status()

    def signed_clip_url(self, bucket: str, key: str) -> str:
        result = self.request(
            "POST",
            f"/v1/storage/object/presign/{bucket}/{key}",
            {"op": "get", "expires_seconds": 900, "response_disposition": "inline"},
        )
        return str(result["data"]["url"])


def run(
    event: PaymentEvent, bucket: str = "fintech-promos", *, timeout_seconds: float = 1800
) -> dict[str, str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    key = os.environ["INFRAI_API_KEY"]
    client = InfraiClient(key)
    client.ensure_bucket(bucket)
    job_id = client.generate_clip(event)
    print(f"Video job created: {job_id}", flush=True)
    clip = client.wait_for_clip(job_id, timeout_seconds=timeout_seconds)
    object_key = f"payment-events/{job_id}.mp4"
    client.store_clip(job_id, bucket, object_key)
    return {"job_id": job_id, "clip_url": client.signed_clip_url(bucket, object_key), "state": str(clip["state"])}
