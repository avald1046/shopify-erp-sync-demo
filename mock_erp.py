"""
Mock ERP system for the portfolio demo.

Exposes a tiny REST-ish API the integration talks to:
  GET  /inventory            -> current on-hand quantities per SKU
  POST /orders               -> create an order, decrement inventory
  GET  /orders               -> list created orders
  POST /chaos/flaky          -> make the next POST /orders fail with 500 (demo retry logic)

Run:  python3 mock_erp.py   (listens on 127.0.0.1:8001)
Zero dependencies — stdlib only.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST, PORT = "127.0.0.1", 8001

# In-memory "database"
INVENTORY = {"SKU-1001": 50, "SKU-1002": 120, "SKU-1003": 8}
ORDERS = []
FLAKY_NEXT = {"count": 0}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/inventory":
            self._send(200, {"inventory": INVENTORY})
        elif self.path == "/orders":
            self._send(200, {"orders": ORDERS})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/orders":
            # Chaos toggle: simulate the ERP being briefly unavailable.
            if FLAKY_NEXT["count"] > 0:
                FLAKY_NEXT["count"] -= 1
                self._send(500, {"error": "simulated ERP outage"})
                return
            order = {
                "erp_order_id": f"ERP-{len(ORDERS) + 1:05d}",
                "shopify_order_id": payload.get("shopify_order_id"),
                "lines": payload.get("lines", []),
            }
            for line in order["lines"]:
                sku, qty = line["sku"], line["quantity"]
                INVENTORY[sku] = INVENTORY.get(sku, 0) - qty
            ORDERS.append(order)
            self._send(201, order)
        elif self.path == "/chaos/flaky":
            FLAKY_NEXT["count"] = int(payload.get("failures", 1))
            self._send(200, {"flaky_next": FLAKY_NEXT["count"]})
        elif self.path == "/inventory/adjust":
            # A human in the warehouse changed stock outside the integration
            # (cycle count, damage, manual correction).
            sku = payload.get("sku")
            INVENTORY[sku] = int(payload.get("quantity", 0))
            self._send(200, {"sku": sku, "quantity": INVENTORY[sku]})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args):
        pass  # keep demo output clean


if __name__ == "__main__":
    print(f"Mock ERP listening on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
