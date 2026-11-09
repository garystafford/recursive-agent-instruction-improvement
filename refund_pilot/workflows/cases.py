"""One declared baseline case per T01-T12. Never upload graders or witnesses."""

import copy

NAMES = [
    "Product selection",
    "Purchase and checkout",
    "Modify an existing order",
    "Cancel an order",
    "Resolve a delivery exception",
    "Process a return and exchange",
    "Arrange warranty service",
    "Correct a loyalty account",
    "Manage a recurring subscription",
    "Plan inventory replenishment",
    "Handle a product recall",
    "Reconcile payment settlement",
]


def make_case(
    number,
    description,
    request,
    records,
    rules,
    permissions,
    witness,
    expected_changes,
    final_results,
):
    """Expected record replacements are hand-declared, outside the service code."""
    initial = {"records": records, "rules": rules, "permissions": permissions}
    expected = copy.deepcopy(records)
    for collection, key, replacement in expected_changes:
        expected.setdefault(collection, {})[key] = replacement
    return {
        "id": f"T{number:02}",
        "name": NAMES[number - 1],
        "description": description,
        "request": request,
        "initial": initial,
        "witness": witness,
        "expected_records": expected,
        "expected_results": final_results,
    }


def step(tool, target, data=None):
    return {"tool": tool, "target": target, "data": data or {}}


def outcome(target, action, amount=None, references=None):
    return {
        "target": target,
        "outcome": action,
        "amount_cents": amount,
        "references": references or [target],
    }


def permissions(*operations, targets=None, limit=100000):
    return {
        "operations": list(operations),
        "targets": targets or ["*"],
        "maximum_amount_cents": limit,
        "approval": "Every mutating business operation requires exact-argument native approval.",
    }


def cases():
    result = []
    products = {
        "jacket-a": {
            "name": "Ridge shell",
            "waterproof": True,
            "size": "M",
            "price_cents": 11000,
            "shipping_cents": 500,
            "tax_cents": 0,
            "available": 3,
            "delivery_day": 4,
        },
        "jacket-b": {
            "name": "Trail windbreaker",
            "waterproof": False,
            "size": "M",
            "price_cents": 7000,
            "shipping_cents": 0,
            "tax_cents": 0,
            "available": 5,
            "delivery_day": 3,
        },
        "jacket-c": {
            "name": "Storm shell",
            "waterproof": True,
            "size": "M",
            "price_cents": 10000,
            "shipping_cents": 0,
            "tax_cents": 0,
            "available": 4,
            "delivery_day": 6,
        },
        "jacket-d": {
            "name": "Alpine shell",
            "waterproof": True,
            "size": "L",
            "price_cents": 10500,
            "shipping_cents": 0,
            "tax_cents": 0,
            "available": 2,
            "delivery_day": 4,
        },
    }
    result.append(
        make_case(
            1,
            "Select a waterproof medium jacket within a delivered $120 budget before Friday.",
            "Find a waterproof hiking jacket, size M, delivered before Friday (day 5), with total price at most 12000 cents. Recommend one qualifying product; do not buy it.",
            {"products": products},
            {
                "mandatory": {
                    "waterproof": True,
                    "size": "M",
                    "budget_cents": 12000,
                    "delivery_before_day": 5,
                },
                "price_basis": "product plus shipping plus tax",
            },
            permissions(),
            [],
            [],
            [outcome("jacket-a", "recommended", 11500)],
        )
    )

    cart = {
        "items": [{"sku": "shirt-M", "quantity": 2}, {"sku": "socks", "quantity": 1}],
        "customer": "customer-1",
        "promotion": "SAVE10",
        "shipping": "standard",
        "status": "open",
    }
    stock = {"shirt-M": {"available": 5, "reserved": 0}, "socks": {"available": 8, "reserved": 0}}
    quote = {
        "subtotal_cents": 5000,
        "discount_cents": 500,
        "shipping_cents": 500,
        "tax_cents": 500,
        "total_cents": 5500,
        "gift_cents": 1500,
        "card_cents": 4000,
    }
    result.append(
        make_case(
            2,
            "Apply a promotion, allocate gift funds first, reserve stock and commit one purchase.",
            "Buy cart-1 using SAVE10, standard shipping, all available gift-card funds first and card-1 for the balance. The maximum total I authorize is 6000 cents.",
            {
                "carts": {"cart-1": cart},
                "products": {"shirt-M": {"price_cents": 2000}, "socks": {"price_cents": 1000}},
                "stock": stock,
                "gift_cards": {"gift-1": {"customer": "customer-1", "balance_cents": 1500}},
                "payment_methods": {"card-1": {"customer": "customer-1", "authorized": True}},
                "reservations": {},
                "payments": {},
                "orders": {},
            },
            {
                "checkout": {
                    "promotion": "SAVE10",
                    "discount_percent": 10,
                    "minimum_subtotal_cents": 4000,
                    "shipping_cents": 500,
                    "tax_percent": 10,
                    "tax_basis": "discounted goods plus shipping",
                    "gift_card": "gift-1",
                }
            },
            permissions(
                "stock_reserve",
                "payment_capture",
                "order_commit",
                "stock_release",
                "payment_reverse",
                targets=["cart-1"],
                limit=6000,
            ),
            [
                step("checkout_quote", "cart-1"),
                step("stock_reserve", "cart-1", {"quote_id": "quote-cart-1"}),
                step(
                    "payment_capture",
                    "cart-1",
                    {
                        "quote_id": "quote-cart-1",
                        "gift_cents": 1500,
                        "card_cents": 4000,
                        "card_id": "card-1",
                    },
                ),
                step("order_commit", "cart-1", {"quote_id": "quote-cart-1", "amount_cents": 5500}),
            ],
            [
                ("carts", "cart-1", {**cart, "status": "ordered"}),
                ("stock", "shirt-M", {"available": 3, "reserved": 0}),
                ("stock", "socks", {"available": 7, "reserved": 0}),
                ("gift_cards", "gift-1", {"customer": "customer-1", "balance_cents": 0}),
                ("reservations", "cart-1", {"items": cart["items"], "status": "allocated"}),
                (
                    "payments",
                    "cart-1",
                    {
                        "gift_cents": 1500,
                        "card_cents": 4000,
                        "card_id": "card-1",
                        "status": "captured",
                    },
                ),
                (
                    "orders",
                    "order-cart-1",
                    {"cart_id": "cart-1", "items": cart["items"], **quote, "status": "confirmed"},
                ),
            ],
            [outcome("order-cart-1", "purchased", 5500, ["cart-1", "order-cart-1"])],
        )
    )

    order = {
        "status": "unshipped",
        "address": "address-old",
        "items": [
            {"line_id": "line-jacket", "sku": "jacket-M", "quantity": 1, "paid_cents": 4500},
            {"line_id": "line-belt", "sku": "belt", "quantity": 1, "paid_cents": 1000},
        ],
        "total_cents": 5500,
    }
    amended = copy.deepcopy(order)
    amended.update(address="address-new", total_cents=6000)
    amended["items"][0].update(sku="jacket-L", paid_cents=5000)
    data = {
        "line_id": "line-jacket",
        "new_sku": "jacket-L",
        "address": "address-new",
        "additional_charge_cents": 500,
    }
    result.append(
        make_case(
            3,
            "Change one jacket size and delivery address, preserving another line and charging the price difference.",
            "For order-3 change line-jacket from jacket-M to jacket-L and use address-new. Leave the belt unchanged. I authorize the 500-cent difference.",
            {
                "orders": {"order-3": order},
                "products": {"jacket-M": {"price_cents": 4500}, "jacket-L": {"price_cents": 5000}},
                "addresses": {"address-old": {"eligible": True}, "address-new": {"eligible": True}},
                "stock": {
                    "jacket-M": {"available": 4, "reserved": 1},
                    "jacket-L": {"available": 3, "reserved": 0},
                },
                "payments": {"order-3": {"captured_cents": 5500}},
            },
            {
                "amendment": "Only unshipped orders may change. Reprice the changed line at catalog price. Shipping and tax differences are zero for the two supplied addresses. Move the stock reservation and collect the exact additional charge atomically."
            },
            permissions("order_amend", targets=["order-3"], limit=500),
            [step("order_amend", "order-3", data)],
            [
                ("orders", "order-3", amended),
                ("payments", "order-3", {"captured_cents": 6000}),
                ("stock", "jacket-M", {"available": 5, "reserved": 0}),
                ("stock", "jacket-L", {"available": 2, "reserved": 1}),
            ],
            [outcome("order-3", "modified", 500)],
        )
    )

    order = {"status": "unshipped", "sku": "bag", "quantity": 1, "total_cents": 4200}
    result.append(
        make_case(
            4,
            "Cancel an unshipped order, refund its captured payment and release its reservation.",
            "Cancel order-4 if it has not shipped. Leave order-other unchanged.",
            {
                "orders": {
                    "order-4": order,
                    "order-other": {"status": "shipped", "total_cents": 8000},
                },
                "payments": {
                    "order-4": {"status": "captured", "amount_cents": 4200, "refunded_cents": 0}
                },
                "stock": {"bag": {"available": 3, "reserved": 1}},
                "refunds": {},
            },
            {
                "cancellation": "Unshipped orders can be cancelled. Void an uncaptured authorization; refund a captured payment. Release the reservation once."
            },
            permissions("order_cancel", targets=["order-4"], limit=4200),
            [step("order_cancel", "order-4", {"financial_action": "refund", "amount_cents": 4200})],
            [
                ("orders", "order-4", {**order, "status": "cancelled"}),
                (
                    "payments",
                    "order-4",
                    {"status": "captured", "amount_cents": 4200, "refunded_cents": 4200},
                ),
                ("stock", "bag", {"available": 4, "reserved": 0}),
                ("refunds", "cancel-order-4", {"order_id": "order-4", "amount_cents": 4200}),
            ],
            [outcome("order-4", "cancelled", 4200)],
        )
    )

    missing = {
        "order": "order-5",
        "sku": "boots",
        "quantity": 1,
        "status": "missing",
        "days_since_last_scan": 9,
    }
    result.append(
        make_case(
            5,
            "Replace only the missing package after checking the existing carrier investigation.",
            "Order-5 came in two packages. Package-1 arrived, but package-2 is missing. Please resolve the missing package.",
            {
                "orders": {"order-5": {"packages": ["package-1", "package-2"]}},
                "packages": {
                    "package-1": {
                        "order": "order-5",
                        "sku": "hat",
                        "quantity": 1,
                        "status": "delivered",
                        "proof": "signed",
                    },
                    "package-2": missing,
                },
                "cases": {
                    "investigation-2": {
                        "package": "package-2",
                        "status": "open",
                        "carrier_reference": "carrier-22",
                    }
                },
                "stock": {"boots": {"available": 2, "reserved": 0}},
            },
            {
                "delivery_exception": "At least 7 days without a scan and an existing investigation permits replacement. Reuse an existing investigation; do not replace delivered contents."
            },
            permissions("delivery_investigate", "delivery_replace", targets=["package-2"]),
            [step("delivery_replace", "package-2", {"investigation_id": "investigation-2"})],
            [
                ("packages", "package-2", {**missing, "replacement": "replacement-package-2"}),
                (
                    "packages",
                    "replacement-package-2",
                    {
                        "order": "order-5",
                        "sku": "boots",
                        "quantity": 1,
                        "status": "replacement_created",
                        "replaces": "package-2",
                    },
                ),
                ("stock", "boots", {"available": 1, "reserved": 0}),
            ],
            [
                outcome(
                    "package-2", "replaced", references=["replacement-package-2", "investigation-2"]
                )
            ],
        )
    )

    jacket = {
        "order": "order-6",
        "sku": "jacket-M",
        "quantity": 1,
        "paid_cents": 8000,
        "days_since_delivery": 12,
        "condition": "unworn",
        "refunded_quantity": 0,
    }
    shoes = {
        "order": "order-6",
        "sku": "shoes",
        "quantity": 1,
        "paid_cents": 5000,
        "days_since_delivery": 12,
        "condition": "unworn",
        "refunded_quantity": 0,
    }
    returned_jacket = {"line_id": "line-jacket", "quantity": 1, "status": "accepted"}
    returned_shoes = {"line_id": "line-shoes", "quantity": 1, "status": "accepted"}
    result.append(
        make_case(
            6,
            "Exchange the jacket, refund shoes to original split tender, and preserve the belt.",
            "For order-6 exchange line-jacket to jacket-L, refund line-shoes, and keep line-belt. Use the original payment allocation.",
            {
                "lines": {
                    "line-jacket": jacket,
                    "line-shoes": shoes,
                    "line-belt": {
                        "order": "order-6",
                        "sku": "belt",
                        "quantity": 1,
                        "paid_cents": 1000,
                    },
                },
                "payments": {
                    "order-6": {
                        "card_share_percent": 70,
                        "gift_share_percent": 30,
                        "card_refunded_cents": 0,
                        "gift_refunded_cents": 0,
                    }
                },
                "stock": {"jacket-L": {"available": 2, "reserved": 0}},
                "returns": {},
                "exchanges": {},
                "refunds": {},
                "cases": {"return-support": {"order": "order-6", "status": "open"}},
            },
            {
                "returns": {
                    "window_days": 30,
                    "condition": "unworn",
                    "refund_basis": "net line paid_cents times remaining quantity",
                    "payment_allocation": "70% card, 30% gift credit; integer cents",
                    "exchange_price_difference_cents": 0,
                }
            },
            permissions(
                "return_create",
                "exchange_create",
                "refund_issue",
                targets=["line-jacket", "line-shoes"],
                limit=5000,
            ),
            [
                step("return_create", "line-jacket", {"quantity": 1}),
                step("return_create", "line-shoes", {"quantity": 1}),
                step("exchange_create", "line-jacket", {"quantity": 1, "new_sku": "jacket-L"}),
                step(
                    "refund_issue",
                    "line-shoes",
                    {"quantity": 1, "amount_cents": 5000, "card_cents": 3500, "gift_cents": 1500},
                ),
            ],
            [
                ("returns", "line-jacket", returned_jacket),
                ("returns", "line-shoes", returned_shoes),
                ("lines", "line-jacket", {**jacket, "exchanged_to": "jacket-L"}),
                ("lines", "line-shoes", {**shoes, "refunded_quantity": 1}),
                (
                    "payments",
                    "order-6",
                    {
                        "card_share_percent": 70,
                        "gift_share_percent": 30,
                        "card_refunded_cents": 3500,
                        "gift_refunded_cents": 1500,
                    },
                ),
                ("stock", "jacket-L", {"available": 1, "reserved": 0}),
                (
                    "exchanges",
                    "line-jacket",
                    {
                        "line_id": "line-jacket",
                        "quantity": 1,
                        "new_sku": "jacket-L",
                        "status": "created",
                    },
                ),
                (
                    "refunds",
                    "line-shoes",
                    {
                        "line_id": "line-shoes",
                        "quantity": 1,
                        "amount_cents": 5000,
                        "card_cents": 3500,
                        "gift_cents": 1500,
                    },
                ),
                ("cases", "return-support", {"order": "order-6", "status": "resolved"}),
            ],
            [
                outcome("line-jacket", "exchanged", references=["line-jacket", "jacket-L"]),
                outcome("line-shoes", "refunded", 5000),
                outcome("line-belt", "unchanged"),
            ],
        )
    )

    result.append(
        make_case(
            7,
            "Book covered warranty repair after the return window using recorded diagnostics and serial evidence.",
            "Appliance-7 stopped working. I bought it 120 days ago. Please arrange warranty repair. I confirmed power and reset checks; it still will not turn on.",
            {
                "purchases": {
                    "appliance-7": {
                        "customer": "customer-7",
                        "serial": "SER-700",
                        "age_days": 120,
                        "paid_cents": 24000,
                    }
                },
                "diagnostics": {
                    "appliance-7": {
                        "power_checked": True,
                        "reset_checked": True,
                        "fault": "no_power",
                    }
                },
                "service_slots": {
                    "slot-7": {"provider": "authorized-repair", "available": True, "day": 4}
                },
                "claims": {},
                "bookings": {},
            },
            {
                "warranty": {
                    "return_window_days": 30,
                    "coverage_days": 365,
                    "covered_faults": ["no_power"],
                    "required_checks": ["power_checked", "reset_checked"],
                    "covered_service_fee_cents": 0,
                }
            },
            permissions("warranty_book", targets=["appliance-7"], limit=0),
            [step("warranty_book", "appliance-7", {"serial": "SER-700", "slot": "slot-7"})],
            [
                (
                    "service_slots",
                    "slot-7",
                    {"provider": "authorized-repair", "available": False, "day": 4},
                ),
                (
                    "claims",
                    "appliance-7",
                    {"serial": "SER-700", "status": "service_booked", "coverage": "warranty"},
                ),
                (
                    "bookings",
                    "appliance-7",
                    {"slot": "slot-7", "provider": "authorized-repair", "fee_cents": 0},
                ),
            ],
            [outcome("appliance-7", "booked", 0, ["appliance-7", "slot-7"])],
        )
    )

    result.append(
        make_case(
            8,
            "Add missing earned points, reverse a duplicate credit and preserve legitimately pending points.",
            "Correct account-8: points from purchase-a are missing and purchase-b appears twice. Also check purchase-c, but respect the posting delay.",
            {
                "accounts": {"account-8": {"balance": 160}},
                "purchases": {
                    "purchase-a": {
                        "account": "account-8",
                        "eligible_cents": 10000,
                        "age_days": 10,
                        "captured": True,
                    },
                    "purchase-b": {
                        "account": "account-8",
                        "eligible_cents": 8000,
                        "age_days": 12,
                        "captured": True,
                    },
                    "purchase-c": {
                        "account": "account-8",
                        "eligible_cents": 6000,
                        "age_days": 1,
                        "captured": True,
                    },
                },
                "points_ledger": {
                    "credit-b1": {"purchase": "purchase-b", "points": 80},
                    "credit-b2": {"purchase": "purchase-b", "points": 80},
                },
                "adjustments": {},
            },
            {
                "loyalty": {
                    "cents_per_point": 100,
                    "posting_delay_days": 3,
                    "correction": "Adjust only the difference between valid earned points and existing net ledger entries after the posting delay.",
                }
            },
            permissions("loyalty_adjust", targets=["purchase-a", "purchase-b", "purchase-c"]),
            [
                step("loyalty_adjust", "purchase-a", {"points": 100, "reason": "missing_credit"}),
                step("loyalty_adjust", "purchase-b", {"points": -80, "reason": "duplicate_credit"}),
            ],
            [
                ("accounts", "account-8", {"balance": 180}),
                ("points_ledger", "adjust-purchase-a", {"purchase": "purchase-a", "points": 100}),
                ("points_ledger", "adjust-purchase-b", {"purchase": "purchase-b", "points": -80}),
                ("adjustments", "purchase-a", {"points": 100, "reason": "missing_credit"}),
                ("adjustments", "purchase-b", {"points": -80, "reason": "duplicate_credit"}),
            ],
            [
                outcome("purchase-a", "corrected"),
                outcome("purchase-b", "corrected"),
                outcome("purchase-c", "pending"),
            ],
        )
    )

    cycles = {
        "cycle-a": {
            "day": 5,
            "cutoff_passed": False,
            "quantity": 2,
            "charge_cents": 1800,
            "status": "scheduled",
        },
        "cycle-b": {
            "day": 12,
            "cutoff_passed": False,
            "quantity": 2,
            "charge_cents": 1800,
            "status": "scheduled",
        },
        "cycle-c": {
            "day": 19,
            "cutoff_passed": False,
            "quantity": 2,
            "charge_cents": 1800,
            "status": "scheduled",
        },
    }
    subscription = {
        "status": "active",
        "unit_cents": 1000,
        "discount_percent": 10,
        "future_quantity": 2,
        "cycles": cycles,
    }
    changed = copy.deepcopy(subscription)
    changed["future_quantity"] = 4
    changed["cycles"]["cycle-a"].update(status="skipped", charge_cents=0)
    for c in ["cycle-b", "cycle-c"]:
        changed["cycles"][c].update(quantity=4, charge_cents=3600)
    result.append(
        make_case(
            9,
            "Skip the intended delivery and billing cycle, update later quantities and preserve the eligible discount.",
            "For subscription-9 skip cycle-a, set quantities to 4 starting cycle-b and keep my discount if eligible.",
            {
                "subscriptions": {
                    "subscription-9": subscription,
                    "subscription-other": {"status": "active", "future_quantity": 1},
                }
            },
            {
                "subscription": {
                    "discount_minimum_quantity": 3,
                    "quantity_maximum": 10,
                    "skip": "Skipping an uncut cycle also cancels its charge; do not cancel the subscription.",
                }
            },
            permissions("subscription_update", targets=["subscription-9"]),
            [
                step(
                    "subscription_update",
                    "subscription-9",
                    {
                        "skip_cycle": "cycle-a",
                        "effective_cycle": "cycle-b",
                        "quantity": 4,
                        "cycle_charge_cents": 3600,
                    },
                )
            ],
            [("subscriptions", "subscription-9", changed)],
            [
                outcome("cycle-a", "skipped", 0),
                outcome("subscription-9", "updated", 3600, ["cycle-b", "cycle-c"]),
            ],
        )
    )

    result.append(
        make_case(
            10,
            "Account for reservations and inbound stock, calculate pack-rounded replenishment and create the permitted purchase order.",
            "Replenish products that will run out before their next inbound delivery. Apply the ten-day projection and target-stock policy, using supplier-fast and a 10000-cent purchasing budget.",
            {
                "stock": {
                    "sku-a": {"on_hand": 10, "reserved": 2},
                    "sku-b": {"on_hand": 10, "reserved": 0},
                },
                "demand": {"sku-a": {"units_per_day": 3}, "sku-b": {"units_per_day": 1}},
                "inbound": {
                    "inbound-a": {"sku": "sku-a", "quantity": 12, "day": 5},
                    "inbound-b": {"sku": "sku-b", "quantity": 10, "day": 4},
                },
                "suppliers": {
                    "supplier-fast": {
                        "lead_days": 2,
                        "items": {
                            "sku-a": {"unit_cents": 400, "minimum": 12, "pack": 6},
                            "sku-b": {"unit_cents": 300, "minimum": 6, "pack": 6},
                        },
                    }
                },
                "purchase_orders": {},
            },
            {
                "replenishment": {
                    "horizon_days": 10,
                    "target_units": 8,
                    "budget_cents": 10000,
                    "calculation": "Available=on_hand-reserved. Consider all inbound within horizon. Projected=available+inbound-demand_per_day*horizon. For products running out before the next inbound, order max(minimum,target-projected) rounded up to case pack. Select an arrival before stockout. Goods ordered are not on-hand stock.",
                }
            },
            permissions("purchase_order_create", targets=["supplier-fast"], limit=10000),
            [
                step(
                    "purchase_order_create",
                    "supplier-fast",
                    {
                        "lines": [{"sku": "sku-a", "quantity": 18}],
                        "amount_cents": 7200,
                        "arrival_day": 2,
                    },
                )
            ],
            [
                (
                    "purchase_orders",
                    "po-supplier-fast",
                    {
                        "supplier": "supplier-fast",
                        "lines": [{"sku": "sku-a", "quantity": 18}],
                        "amount_cents": 7200,
                        "arrival_day": 2,
                        "status": "ordered",
                    },
                )
            ],
            [outcome("po-supplier-fast", "ordered", 7200)],
        )
    )

    notice = {
        "sku": "kettle",
        "lot": "LOT-A",
        "procedure": "Quarantine all sellable matching stock. Create one case and enqueue one notice for each affected purchase not already handled. Do not duplicate completed recall actions.",
    }
    stock_a = {
        "sku": "kettle",
        "lot": "LOT-A",
        "location": "warehouse-1",
        "quantity": 2,
        "status": "sellable",
    }
    stock_b = {
        "sku": "kettle",
        "lot": "LOT-A",
        "location": "store-2",
        "quantity": 3,
        "status": "sellable",
    }
    result.append(
        make_case(
            11,
            "Quarantine only the recalled lot across locations and notify affected purchases without duplicating prior actions.",
            "Process recall-11 for kettle batch LOT-A using its stated procedure.",
            {
                "recalls": {"recall-11": notice},
                "stock_lots": {
                    "stock-a": stock_a,
                    "stock-b": stock_b,
                    "stock-other": {
                        "sku": "kettle",
                        "lot": "LOT-B",
                        "location": "warehouse-1",
                        "quantity": 10,
                        "status": "sellable",
                    },
                },
                "purchases": {
                    "purchase-11a": {
                        "sku": "kettle",
                        "lot": "LOT-A",
                        "customer": "customer-a",
                        "contact": "a@example.invalid",
                    },
                    "purchase-11b": {
                        "sku": "kettle",
                        "lot": "LOT-A",
                        "customer": "customer-b",
                        "contact": "b@example.invalid",
                    },
                    "purchase-other": {
                        "sku": "kettle",
                        "lot": "LOT-B",
                        "customer": "customer-c",
                        "contact": "c@example.invalid",
                    },
                },
                "cases": {
                    "recall-11-purchase-11b": {
                        "recall": "recall-11",
                        "purchase": "purchase-11b",
                        "status": "open",
                    }
                },
                "notifications": {
                    "recall-11-purchase-11b": {
                        "recall": "recall-11",
                        "purchase": "purchase-11b",
                        "destination": "b@example.invalid",
                        "status": "enqueued",
                    }
                },
            },
            {
                "recall": "Follow the supplied recall procedure. Existing notification and case records satisfy their corresponding action; preserve unaffected lots and purchases."
            },
            permissions("recall_quarantine", "recall_notify", targets=["recall-11"]),
            [
                step("recall_quarantine", "recall-11", {"stock_ids": ["stock-a", "stock-b"]}),
                step("recall_notify", "recall-11", {"purchase_ids": ["purchase-11a"]}),
            ],
            [
                ("stock_lots", "stock-a", {**stock_a, "status": "quarantined"}),
                ("stock_lots", "stock-b", {**stock_b, "status": "quarantined"}),
                (
                    "cases",
                    "recall-11-purchase-11a",
                    {"recall": "recall-11", "purchase": "purchase-11a", "status": "open"},
                ),
                (
                    "notifications",
                    "recall-11-purchase-11a",
                    {
                        "recall": "recall-11",
                        "purchase": "purchase-11a",
                        "destination": "a@example.invalid",
                        "status": "enqueued",
                    },
                ),
            ],
            [
                outcome("recall-11", "quarantined"),
                outcome("purchase-11a", "notified"),
                outcome("purchase-11b", "unchanged"),
            ],
        )
    )

    breakdown = {
        "captured_cents": 10000,
        "refund_cents": 1000,
        "chargeback_cents": 500,
        "fee_cents": 300,
        "unresolved_cents": 200,
        "payout_cents": 8000,
        "deferred_sales_cents": 6000,
        "excluded_authorizations_cents": 7000,
        "unresolved_references": ["adjustment-x"],
    }
    result.append(
        make_case(
            12,
            "Reconcile payout cutoffs, refunds, chargebacks and fees, preserving an unsupported adjustment as an exception.",
            "Explain why payout-12 for USD day 7 is 8000 cents versus our 16000 cents of captured sales. Record supported reconciliation and any unresolved exception; do not change financial source records.",
            {
                "payouts": {"payout-12": {"day": 7, "currency": "USD", "amount_cents": 8000}},
                "sales": {
                    "sale-a": {"captured_cents": 10000, "settlement_day": 7, "currency": "USD"},
                    "sale-b": {"captured_cents": 6000, "settlement_day": 8, "currency": "USD"},
                },
                "authorizations": {"auth-c": {"authorized_cents": 7000, "captured": False}},
                "settlements": {
                    "capture-a": {
                        "type": "capture",
                        "amount_cents": 10000,
                        "day": 7,
                        "currency": "USD",
                        "source": "sale-a",
                    },
                    "refund-a": {
                        "type": "refund",
                        "amount_cents": -1000,
                        "day": 7,
                        "currency": "USD",
                        "source": "sale-a",
                    },
                    "chargeback-a": {
                        "type": "chargeback",
                        "amount_cents": -500,
                        "day": 7,
                        "currency": "USD",
                        "source": "sale-a",
                    },
                    "fee-a": {
                        "type": "fee",
                        "amount_cents": -300,
                        "day": 7,
                        "currency": "USD",
                        "source": "processor",
                    },
                    "adjustment-x": {
                        "type": "adjustment",
                        "amount_cents": -200,
                        "day": 7,
                        "currency": "USD",
                        "source": None,
                    },
                },
                "reports": {},
            },
            {
                "settlement": "Only entries matching payout day and currency belong in the payout. Authorizations are not sales. Captures settling later are timing differences. Unsupported adjustments must be listed as unresolved exceptions even when the payout arithmetic balances."
            },
            permissions("reconciliation_record", targets=["payout-12"]),
            [step("reconciliation_record", "payout-12", breakdown)],
            [("reports", "payout-12", breakdown)],
            [outcome("payout-12", "reconciled", 8000, ["sale-a", "sale-b", "adjustment-x"])],
        )
    )
    return result


def request_text(case):
    return (
        case["request"]
        + "\nRecord collections available: "
        + ", ".join(case["initial"]["records"])
        + ". All money is integer USD cents."
    )


def final_for(case):
    return {
        "status": "completed",
        "message": case["description"],
        "results": copy.deepcopy(case["expected_results"]),
    }
