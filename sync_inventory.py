"""
Nightly inventory reconciliation job (the other half of the demo).

Pulls on-hand quantities from the ERP and pushes them to the storefront so
the website never sells what the warehouse doesn't have. Webhooks handle the
real-time path; this job is the safety net that catches anything webhooks
missed (missed deliveries, manual ERP adjustments, etc.).

Here the "storefront" is simulated with a local JSON file standing in for
the Shopify Admin API's inventorySetOnHandQuantities mutation — the request
payloads printed are exactly what would be sent to Shopify.

Run:  python3 sync_inventory.py
Zero dependencies — stdlib only.
"""
import json
import urllib.request

ERP_BASE_URL = "http://127.0.0.1:8001"
SHOPIFY_INVENTORY_FILE = "shopify_inventory.json"


def erp_get(path):
    with urllib.request.urlopen(ERP_BASE_URL + path, timeout=5) as resp:
        return json.loads(resp.read())


def main():
    erp_inventory = erp_get("/inventory")["inventory"]

    try:
        with open(SHOPIFY_INVENTORY_FILE) as f:
            shopify_inventory = json.load(f)
    except FileNotFoundError:
        shopify_inventory = {}

    updates = []
    for sku, qty in erp_inventory.items():
        if shopify_inventory.get(sku) != qty:
            updates.append(sku)
            # This is the payload shape sent to Shopify's
            # inventorySetOnHandQuantities mutation (simplified):
            mutation = {
                "input": {
                    "reason": "correction",
                    "setQuantities": [{"inventoryItemId": f"gid://shopify/InventoryItem/{sku}",
                                       "locationId": "gid://shopify/Location/1",
                                       "quantity": qty}],
                }
            }
            print(f"  [sync] {sku}: {shopify_inventory.get(sku, '—')} -> {qty}")
            print(f"         would send: {json.dumps(mutation['input']['setQuantities'][0])}")
            shopify_inventory[sku] = qty

    with open(SHOPIFY_INVENTORY_FILE, "w") as f:
        json.dump(shopify_inventory, f, indent=2)

    if updates:
        print(f"  [sync] reconciled {len(updates)} SKU(s): {', '.join(updates)}")
    else:
        print("  [sync] already in sync — nothing to do")


if __name__ == "__main__":
    main()
