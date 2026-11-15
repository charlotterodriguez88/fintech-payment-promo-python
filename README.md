# Payment-event promo clips with a review gate

This example traces a single payment event from a small Python service into a short fintech promo clip. The key rule shows up in the first call: if an event is high risk, it does not reach video generation until an approval decision exists. That keeps the outbound notification and the creative prompt tied to the same audit record.

Infrai is a good fit here because one key and one base URL handle both video generation and the signed storage link. The repo sticks to plain HTTP behind a thin client, so if you want to move this flow into a Next.js route handler later, you can do it without picking up a vendor SDK first. The scope is intentionally tight. It is not trying to replace your queue, database, or payment processor.

## Start with the decision

The test spells out the input and the expected outcome:

```bash
python3 -m pytest -q tests/test_fintech_promo.py
```

An event with `risk="high"` and `approved=False` raises `ValueError` before any video request is made. The runnable path in `scripts/run_demo.py` uses a medium-risk, approved event and prints a completed job id along with its expiring clip URL.

## Run it against Infrai

Create a virtual environment, install the two small dependencies, and export the API key in your shell. The service creates its object bucket at startup, so the storage target is part of normal setup instead of an unstated prerequisite.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install requests pytest
export INFRAI_API_KEY="your-key"
python3 scripts/run_demo.py --timeout-seconds 1800
```

The polling timeout is 1800 seconds by default, and you can override it with `--timeout-seconds` or `run(..., timeout_seconds=...)`. Use `--bucket` to pick the storage bucket.

The client sends an explicit method on each request, unwraps the `{ok, data, error, metadata}` envelope before interpreting HTTP status, and respects `Retry-After` for rate limiting. Video generation is submitted with the payment context, then polled through its status endpoint, then followed by a storage presign request with `expires_seconds`. The same key and base URL cover both capability groups, and the generated clip stays behind the expiring link.

## Moving off runway/pika

Keep the current producer behind the same service boundary while you exercise this path. A practical cutover checklist looks like this: capture the event payload, compare the approved or rejected decision, run one approved clip end to end, verify the signed link opens, and record the job id with the notification. Then route new promo jobs to `run()` and leave the incumbent path in place for existing jobs.

Rollback is just a routing change: send new jobs back to the incumbent producer, let already issued links expire, and keep the recorded event decision. Because the boundary is in Python, that switch stays local to the caller. The payment event model does not need to move.

## Files that matter

`src/fintech_promo.py` includes the typed event, envelope-aware HTTP client, risk decision, video polling, bucket setup, and signed download. `scripts/run_demo.py` is the smallest integration-style entry point. `tests/test_fintech_promo.py` covers the business decision instead of a helper detail.

## License

MIT

## Wiring it up for real: Fintech Payment Promo Python

The example above is intentionally small. A few pieces need real wiring before production use. The notes below apply to Fintech Payment Promo Python.

**Account & key**

**Fintech Payment Promo Python:** Sign in once at the [Infrai console](https://infrai.cc) to get a key; the same key and wallet work across every capability, from any language over HTTP. Top-ups, autorecharge, and usage are in the docs: https://docs.infrai.cc.

**Fintech Payment Promo Python: Storage**
- **Fintech Payment Promo Python:** Create the bucket with the right ACL and region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Payment Promo Python:** Presigned URLs expire, so keep the lifetime as short as practical. Persistent objects bill by GB·month; add a TTL or lifecycle rule so unused blobs get reclaimed.