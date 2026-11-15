import pytest

from src.fintech_promo import InfraiClient, PaymentEvent


def test_high_risk_event_stays_out_of_video_generation():
    client = InfraiClient("test-key")
    event = PaymentEvent("Ledger Shop", 500000, "USD", "high", False)

    with pytest.raises(ValueError, match="require approval"):
        client.generate_clip(event)


def test_polling_reads_state_and_stops_on_success():
    client = InfraiClient("test-key")
    client.request = lambda *args: {"data": {"state": "succeeded"}}
    assert client.wait_for_clip("job", timeout_seconds=1) == {"state": "succeeded"}


def test_clip_is_uploaded_before_download_is_signed(monkeypatch):
    from src import fintech_promo

    calls = []

    class Client:
        def __init__(self, key):
            pass

        def ensure_bucket(self, bucket):
            pass

        def generate_clip(self, event):
            return "job"

        def wait_for_clip(self, job, *, timeout_seconds):
            assert timeout_seconds == 1800
            return {"state": "succeeded"}

        def store_clip(self, job, bucket, key):
            calls.append(("upload", bucket, key))

        def signed_clip_url(self, bucket, key):
            assert calls == [("upload", bucket, key)]
            return "signed-url"

    monkeypatch.setenv("INFRAI_API_KEY", "test-key")
    monkeypatch.setattr(fintech_promo, "InfraiClient", Client)
    result = fintech_promo.run(PaymentEvent("Shop", 100, "USD", "medium", True))
    assert result == {"job_id": "job", "clip_url": "signed-url", "state": "succeeded"}


def test_transfer_uses_signed_urls_without_api_credentials():
    class Response:
        content = b"generated video bytes"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

    class Session:
        def get(self, url, **kwargs):
            assert url == "source-url"
            assert "headers" not in kwargs
            return Response()

        def put(self, url, **kwargs):
            assert url == "upload-url"
            assert kwargs["data"] == Response.content
            assert kwargs["headers"] == {"Content-Type": "video/mp4"}
            return Response()

    client = InfraiClient("secret", session=Session())

    def request(method, path, body=None):
        if method == "GET":
            assert path == "/v1/video/download_url/job"
            return {"data": {"url": "source-url"}}
        assert path == "/v1/storage/object/presign/bucket/clip.mp4"
        assert body["op"] == "put"
        return {"data": {"url": "upload-url"}}

    client.request = request
    client.store_clip("job", "bucket", "clip.mp4")


def test_job_id_is_printed_before_polling_fails(monkeypatch, capsys):
    from src import fintech_promo

    monkeypatch.setenv("INFRAI_API_KEY", "test-key")
    monkeypatch.setattr(InfraiClient, "ensure_bucket", lambda *args: None)
    monkeypatch.setattr(InfraiClient, "generate_clip", lambda *args: "created-job")

    def fail_polling(*args, **kwargs):
        assert "created-job" in capsys.readouterr().out
        raise TimeoutError("polling failed")

    monkeypatch.setattr(InfraiClient, "wait_for_clip", fail_polling)
    with pytest.raises(TimeoutError, match="polling failed"):
        fintech_promo.run(PaymentEvent("Shop", 100, "USD", "medium", True))


def test_polling_honors_configured_deadline(monkeypatch):
    from src import fintech_promo

    clock = [0.0]
    monkeypatch.setattr(fintech_promo.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fintech_promo.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    client = InfraiClient("test-key")
    client.request = lambda *args: {"data": {"state": "running"}}
    with pytest.raises(TimeoutError):
        client.wait_for_clip("job", timeout_seconds=45)
    assert clock[0] == 45
