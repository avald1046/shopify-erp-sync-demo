#!/usr/bin/env bash
# End-to-end demo of the Shopify -> ERP integration.
# Run:  bash demo.sh
set -u
cd "$(dirname "$0")"

SECRET="demo-secret-key"
ERP="http://127.0.0.1:8001"
INTEGRATION="http://127.0.0.1:8000"

sign_and_send() {
  # $1 = order id, $2 = sku, $3 = qty, [$4 = tampered signature?]
  local body sig
  body=$(python3 -c "
import json
print(json.dumps({'id': '$1', 'line_items': [{'sku': '$2', 'quantity': $3}]}))")
  if [ "${4:-}" = "tampered" ]; then
    sig="bogus-signature"
  else
    sig=$(python3 -c "
import base64, hashlib, hmac
body = '''$body'''.encode()
print(base64.b64encode(hmac.new(b'$SECRET', body, hashlib.sha256).digest()).decode())")
  fi
  curl -s -o /dev/null -w "%{http_code}" -X POST "$INTEGRATION/webhooks/orders/create" \
    -H "Content-Type: application/json" \
    -H "X-Shopify-Hmac-Sha256: $sig" \
    -d "$body"
}

echo "== starting mock ERP and integration service =="
python3 mock_erp.py >/tmp/erp.log 2>&1 &
ERP_PID=$!
python3 webhook_server.py >/tmp/integration.log 2>&1 &
INT_PID=$!
trap 'kill $ERP_PID $INT_PID 2>/dev/null' EXIT
sleep 1

echo ""
echo "== 1. Happy path: a real Shopify order webhook arrives =="
code=$(sign_and_send "order-9001" "SKU-1001" 2)
echo "   webhook response: HTTP $code"
echo "   ERP inventory now: $(curl -s $ERP/inventory | python3 -c 'import json,sys; print(json.load(sys.stdin)["inventory"])')"

echo ""
echo "== 2. Security: a forged webhook (bad signature) is rejected =="
code=$(sign_and_send "order-evil" "SKU-1001" 1 "tampered")
echo "   webhook response: HTTP $code  (expected 401)"

echo ""
echo "== 3. Reliability: ERP goes down, integration retries and succeeds =="
curl -s -X POST "$ERP/chaos/flaky" -H "Content-Type: application/json" -d '{"failures": 2}' >/dev/null
code=$(sign_and_send "order-9002" "SKU-1002" 5)
echo "   webhook response: HTTP $code  (ERP failed twice, retry won)"

echo ""
echo "== 4. Idempotency: Shopify redelivers the same webhook =="
code=$(sign_and_send "order-9002" "SKU-1002" 5)
echo "   webhook response: HTTP $code  (duplicate detected, no double order)"
echo "   ERP orders: $(curl -s $ERP/orders | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["orders"]))') total (expected 2, not 3)"

echo ""
echo "== 5. Safety net: nightly inventory reconciliation =="
echo "   (warehouse manually adjusts SKU-1003 outside the integration)"
curl -s -X POST "$ERP/inventory/adjust" -H "Content-Type: application/json" \
  -d '{"sku": "SKU-1003", "quantity": 3}' >/dev/null
python3 sync_inventory.py

echo ""
echo "== integration service log =="
grep -E "webhook|retry" /tmp/integration.log | sed 's/^/   /'
echo ""
echo "Demo complete."
