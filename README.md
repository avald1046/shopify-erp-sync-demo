# Shopify → ERP Order & Inventory Sync — Demo

A small, runnable demonstration of the kind of integration work I do for
ecommerce brands: connecting a storefront to the backend systems that fulfill
orders, with the reliability engineering that keeps it from breaking at 2am.

**Zero dependencies.** Python 3 + curl only. No Shopify store or ERP needed —
both sides are simulated so you can run the whole thing locally.

## What it demonstrates

| Scenario | Where to look |
|---|---|
| Order webhooks flow from store → integration → ERP | `webhook_server.py` |
| Webhook authenticity verified via HMAC-SHA256 (Shopify's real scheme) | `verify_signature()` |
| Duplicate webhook deliveries never create double orders | `PROCESSED` idempotency store |
| Transient ERP outages are absorbed with exponential-backoff retries | `create_erp_order_with_retry()` |
| Nightly reconciliation catches anything webhooks missed (manual warehouse adjustments) | `sync_inventory.py` |

## Architecture

```
 Shopify store                Integration service              ERP
 (simulated                   (webhook_server.py)              (mock_erp.py)
  webhook sender)
       | orders/create                | POST /orders
       | + HMAC signature             | (with retries)
       +----------------------------->+-------------------------->
       |                          idempotency check
       |                          signature verification
       |
       |                        nightly: pull inventory, push to
       |                        storefront  (sync_inventory.py)
       |<--------------------------------------------------------+
```

## Run it

```bash
bash demo.sh
```

The script walks through five scenarios: the happy path, a forged webhook
(rejected with 401), an ERP outage (retries win), a duplicate delivery (no
double order), and a manual warehouse adjustment caught by reconciliation.

## Files

- `mock_erp.py` — stand-in ERP: inventory + orders API, with a chaos toggle
  to simulate outages
- `webhook_server.py` — the integration itself: receives webhooks, verifies,
  dedupes, forwards with retries
- `sync_inventory.py` — nightly reconciliation job
- `demo.sh` — scripted end-to-end walkthrough
