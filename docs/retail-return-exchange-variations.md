# Retail return-and-exchange variation catalog

This is the current catalog of the original twelve variations of the retail return-and-exchange workflow. It accompanies the [twelve distinct retail workflows](retail-workflow-study-specification.md) and uses the [current general protocol](cumulative-instruction-improvement-protocol.md) for future experiments.

These are twelve variations within one workflow, not twelve different retail workflows. Every variation starts from the shared request to exchange one item, refund another, and leave a third unchanged, with the additional conditions listed below. The agent uses shared instructions across variations; development and evaluation use separate case data.

The IDs V01-V12 map directly to `family` values 1-12 and the `FAMILIES` entries in [fixtures.py](../refund_pilot/retail/fixtures.py). The source names are retained to make the mapping unambiguous.

| ID | Source family | Variation | Required outcome or distinction |
| --- | --- | --- | --- |
| V01 | `mixed_request` | Exchange, refund, and keep requests together | Complete the requested exchange and refund while preserving the item the customer wants to keep. |
| V02 | `ambiguous_item` | Two matching product descriptions on different orders | Resolve the intended item from the customer's clarification; leave the matching item on the other order unchanged. |
| V03 | `changed_size` | Customer changes the requested exchange size | Apply the latest requested size rather than the superseded size. |
| V04 | `unavailable_size` | The revised exchange size is unavailable | Keep the affected item as the customer requested; do not substitute a refund or the original exchange size. |
| V05 | `split_tender` | Purchase paid with card and gift credit | Allocate refunds to the required original payment methods, despite the customer's preference to move gift credit onto the card. |
| V06 | `multiple_orders` | Multiple orders with a prior partial refund | Refund only the remaining eligible quantity and preserve correct cumulative payment allocation. |
| V07 | `different_windows` | Apparel and electronics have different return windows | Complete eligible apparel actions and deny the out-of-window electronics refund. |
| V08 | `exchange_only` | Opened software has an exchange-only exception | Use the explicitly authorized same-title exchange instead of an ineligible refund; handle other eligible items under their own rules. |
| V09 | `jewelry_inspection` | Jewelry refund awaits an inspection event | Wait for the supplied approved inspection event before completing the jewelry refund. |
| V10 | `final_sale` | Altered jewelry is final sale | Deny the jewelry refund while completing unrelated eligible actions. |
| V11 | `policy_version` | Purchases are governed by different policy versions | Apply each item's recorded policy version: the newer electronics policy denies one item while the older policy permits the other. |
| V12 | `combined` | Size revision, split payment, expired electronics window, and pending jewelry inspection | Apply the latest authorized exchange, preserve required refund allocation, deny the expired electronics refund, and leave jewelry awaiting inspection because no approving event is supplied. |

## Required capabilities and success checks

The catalog uses the return-and-exchange capabilities and checks in T06 of the distinct workflow specification: read purchases and line-level details, retrieve the applicable policy version, check replacement stock, quote exchanges and refunds, inspect return-receipt and jewelry-inspection state, handle approvals, commit authorized actions, and inspect resulting order, payment, inventory, and support records.

Evaluate every requested item independently. Check the selected item and order, action, quantity, replacement variant, refund amount and original payment allocation, approval order, inspection prerequisites, final business state, and truthful customer reporting. Verify that kept, denied, pending, unrelated, and previously refunded items are not changed improperly and that actions are not duplicated.

The case source defines the fictional retailer's policies and variation semantics. Exact identifiers, product descriptions, dates, prices, and payment proportions can differ between development and evaluation cases while preserving the intended conditions. Historical case generators may supply reference examples; their embedded execution schedules and retention rules do not replace the current protocol.
