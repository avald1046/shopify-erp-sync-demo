"""
Shopify -> ERP integration service (the portfolio demo's "product").

Receives Shopify-style `orders/create` webhooks and forwards them to the ERP.

Production-grade behaviors demonstrated:
  1. HMAC-SHA256 signature verification (exactly how Shopify signs webhooks),
     rejecting anything that didn't come from the store.
  2. Idempotency: Shopify retries webhooks, so the same order id is never
     forwarded twice.
  3. Retries with exponential backoff when the ERP is down, so a brief
     outage doesn't lose orders.

Run:  python3 webhook_server.py   (listens on 127.0.0.1:8000)
Env:  SHOPIFY_WEBHOOK_SECRET (default: "demo-secret-key")
      ERP_BASE_URL (default: "http://127.0.0.1:8001")
Zero dependencies — stdlib only.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST, PORT = "127.0.0.1", 8000
SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET", "demo-secret-key").encode()
ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "http://127.0.0.1:8001")

# Idempotency store: shopify order id -> erp order record.
# (In production this is a database table; in-memory is fine for the demo.)
PROCESSED = {}


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Shopify signs the raw body with HMAC-SHA256 and base64-encodes it."""
    digest = hmac.new(SECRET, raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature or "")


def erp_request(method, path, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        ERP_BASE_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


def create_erp_order_with_retry(order_payload, attempts=4, base_delay=0.5):
    """Forward the order to the ERP, retrying transient failures."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            status, body = erp_request("POST", "/orders", order_payload)
            if status in (200, 201):
                return body
            last_error = f"ERP returned {status}"
        except urllib.error.HTTPError as e:
            last_error = f"ERP HTTP {e.code}"
        except Exception as e:  # connection refused, timeout, ...
            last_error = f"ERP unreachable: {e}"
        delay = base_delay * (2 ** (attempt - 1))
        print(f"  [retry] attempt {attempt} failed ({last_error}); "
              f"waiting {delay:.1f}s", flush=True)
        time.sleep(delay)
    raise RuntimeError(f"ERP order creation failed after {attempts} attempts: {last_error}")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "processed_orders": len(PROCESSED)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhooks/orders/create":
            self._send(404, {"error": "not found"})
            return

        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))

        # 1. Verify the webhook actually came from Shopify.
        signature = self.headers.get("X-Shopify-Hmac-Sha256", "")
        if not verify_signature(raw, signature):
            print("  [webhook] REJECTED: bad signature", flush=True)
            self._send(401, {"error": "invalid signature"})
            return

        order = json.loads(raw or b"{}")
        shopify_id = str(order.get("id"))
        print(f"  [webhook] received order {shopify_id}", flush=True)

        # 2. Idempotency: Shopify redelivers webhooks; never double-create.
        if shopify_id in PROCESSED:
            print(f"  [webhook] duplicate of {shopify_id} — already processed, skipping",
                  flush=True)
            self._send(200, {"status": "duplicate", "erp_order": PROCESSED[shopify_id]})
            return

        lines = [
            {"sku": li["sku"], "quantity": li["quantity"]}
            for li in order.get("line_items", [])
        ]

        # 3. Forward to ERP with retries; a 500 here tells Shopify to retry later.
        try:
            erp_order = create_erp_order_with_retry(
                {"shopify_order_id": shopify_id, "lines": lines})
        except RuntimeError as e:
            print(f"  [webhook] FAILED for {shopify_id}: {e}", flush=True)
            self._send(500, {"error": str(e)})
            return

        PROCESSED[shopify_id] = erp_order
        print(f"  [webhook] order {shopify_id} -> {erp_order['erp_order_id']}", flush=True)
        self._send(200, {"status": "ok", "erp_order": erp_order})

    def log_message(self, *args):
        pass  # keep demo output clean


if __name__ == "__main__":
    print(f"Integration service listening on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
