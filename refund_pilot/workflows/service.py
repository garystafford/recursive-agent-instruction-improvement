"""Hosted MCP business simulation. No fixture answers or model credentials here."""

import argparse
import asyncio
import copy
import hashlib
import json
import sqlite3
import time
import zipfile
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

WRITES = {
    "stock_reserve": "Reserve a cart's quoted stock. data_json: {quote_id}.",
    "stock_release": "Release an unallocated cart reservation. data_json: {}.",
    "payment_capture": "Apply gift funds first and capture the authorized card balance after reserving stock. data_json: {quote_id,gift_cents,card_cents,card_id}.",
    "payment_reverse": "Reverse an incomplete cart payment before order commitment. data_json: {}.",
    "order_commit": "Commit a paid and reserved cart once. data_json: {quote_id,amount_cents} with the quoted total.",
    "order_amend": "Atomically amend one eligible order line, address, reservation and exact payment difference. data_json: {line_id,new_sku,address,additional_charge_cents}.",
    "order_cancel": "Cancel eligible fulfillment, release stock and refund a captured payment or void an authorization. data_json: {financial_action: refund|void,amount_cents} with the actual reversal amount.",
    "delivery_investigate": "Open a carrier investigation for a missing package, reusing an existing investigation. data_json: {}.",
    "delivery_replace": "Create a permitted replacement of the missing package only. data_json: {investigation_id}.",
    "return_create": "Accept an eligible line-level return. data_json: {quantity}.",
    "exchange_create": "Create a replacement exchange after an accepted return, allocating the requested stock. data_json: {quantity,new_sku}.",
    "refund_issue": "Refund a returned eligible line to its original payment allocation. data_json: {quantity,amount_cents,card_cents,gift_cents}.",
    "warranty_book": "Create a covered warranty claim and book an available service slot after required recorded diagnostics. data_json: {serial,slot}.",
    "loyalty_adjust": "Post a supported net ledger correction, linked to the qualifying purchase. data_json: {points,reason}.",
    "subscription_update": "Skip the selected eligible cycle and update quantities starting the effective cycle, preserving eligible discounts. data_json: {skip_cycle,effective_cycle,quantity,cycle_charge_cents} with the resulting normal cycle charge.",
    "purchase_order_create": "Create a purchasing order with supplied pack-rounded lines and declared total/arrival; does not receive stock. data_json: {lines:[{sku,quantity}],amount_cents,arrival_day}.",
    "recall_quarantine": "Quarantine the identified affected stock records. data_json: {stock_ids:[ids]}.",
    "recall_notify": "Create affected-purchase recall cases and enqueue simulated notifications without duplicates. data_json: {purchase_ids:[ids]}.",
    "reconciliation_record": "Record a payout reconciliation, preserving all source financial records. data_json: {captured_cents,refund_cents,chargeback_cents,fee_cents,unresolved_cents,payout_cents,deferred_sales_cents,excluded_authorizations_cents,unresolved_references:[ids]}.",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def binding(operation, target, data, key):
    return hashlib.sha256(canonical([operation, target, data, key]).encode()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def amount(data):
    return max(
        [
            abs(data.get(k, 0))
            for k in [
                "amount_cents",
                "additional_charge_cents",
                "card_cents",
                "gift_cents",
                "cycle_charge_cents",
            ]
        ]
        + [data.get("card_cents", 0) + data.get("gift_cents", 0), 0]
    )


def approval_decision(initial, operation, target, data, key, approval_id):
    """Consent checks scope/permission and amount ceiling, never expected answers."""
    permissions = initial["permissions"]
    approved = (
        operation in permissions["operations"]
        and ("*" in permissions["targets"] or target in permissions["targets"])
        and amount(data) <= permissions["maximum_amount_cents"]
        and bool(key)
    )
    return {
        "decision": "approved" if approved else "rejected",
        "approval_id": approval_id,
        "operation": operation,
        "target": target,
        "data": data,
        "idempotency_key": key,
        "binding": binding(operation, target, data, key),
        "amount_cents": amount(data),
        "decided_at_unix": time.time(),
    }


class BusinessService:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.db = sqlite3.connect(self.directory / "business.sqlite")

    @classmethod
    def initialize(cls, directory, initial):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "approvals").mkdir(exist_ok=True)
        db = sqlite3.connect(directory / "business.sqlite")
        db.executescript(
            "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT); CREATE TABLE journal (id INTEGER PRIMARY KEY, payload TEXT); CREATE TABLE operations (key TEXT PRIMARY KEY, binding TEXT, result TEXT);"
        )
        db.execute("INSERT INTO state VALUES (1,?)", (json.dumps(initial),))
        db.commit()
        db.close()
        (directory / "initial-state.json").write_text(json.dumps(initial))
        service = cls(directory)
        service.export()
        service.db.close()

    def state(self):
        return json.loads(self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()[0])

    def export(self):
        state = self.state()
        journal = [
            json.loads(row[0]) for row in self.db.execute("SELECT payload FROM journal ORDER BY id")
        ]
        outputs = self.directory.parent / "outputs"
        outputs.mkdir(exist_ok=True)
        path = outputs / "evidence.tmp"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("state.json", json.dumps(state))
            archive.writestr("journal.json", json.dumps(journal))
            archive.writestr(
                "initial-state.json", (self.directory / "initial-state.json").read_bytes()
            )
            archive.writestr(
                "approvals.json",
                json.dumps(
                    [
                        json.loads(p.read_text())
                        for p in sorted((self.directory / "approvals").glob("*.json"))
                    ]
                ),
            )
        path.replace(outputs / "evidence.zip")

    def invoke(self, tool, args):
        started = time.time()
        initial = self.state()
        state = copy.deepcopy(initial)
        approval = None
        result = None
        try:
            if tool == "policy_get":
                result = state["rules"]
            elif tool == "permissions_get":
                result = state["permissions"]
            elif tool == "records_read":
                result = state["records"][args["collection"]][args["record_id"]]
            elif tool == "records_search":
                filters = json.loads(args.get("filters_json", "{}"))
                result = {
                    k: v
                    for k, v in state["records"].get(args["collection"], {}).items()
                    if all(v.get(field) == value for field, value in filters.items())
                }
            elif tool == "checkout_quote":
                result = self.checkout_quote(state, args["target"])
            elif tool in WRITES:
                target, key = args["target"], args["idempotency_key"]
                data = json.loads(args["data_json"])
                need(isinstance(data, dict), "data_json must encode an object")
                digest = binding(tool, target, data, key)
                approval_id = args["approval_id"]
                need(
                    approval_id.isalnum() or approval_id.replace("-", "").isalnum(),
                    "Invalid approval identifier",
                )
                approval_path = self.directory / "approvals" / (approval_id + ".json")
                need(approval_path.is_file(), "Native approval is required before this action")
                approval = json.loads(approval_path.read_text())
                need(
                    approval["decision"] == "approved" and approval["binding"] == digest,
                    "Approval does not cover these exact arguments",
                )
                p = state["permissions"]
                need(
                    tool in p["operations"] and ("*" in p["targets"] or target in p["targets"]),
                    "Permission denied",
                )
                need(amount(data) <= p["maximum_amount_cents"], "Amount exceeds permission")
                previous = self.db.execute(
                    "SELECT binding,result FROM operations WHERE key=?", (key,)
                ).fetchone()
                if previous:
                    need(previous[0] == digest, "Idempotency key reused for a different action")
                    result = json.loads(previous[1])
                else:
                    result = self.mutate(state, tool, target, data)
                    self.db.execute(
                        "INSERT INTO operations VALUES (?,?,?)", (key, digest, json.dumps(result))
                    )
            else:
                raise ValueError("Unknown business tool")
            self.db.execute("UPDATE state SET payload=? WHERE id=1", (json.dumps(state),))
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            # Roll back every partial multi-record action before returning a rejected operation.
            self.db.rollback()
            result = {"error": type(exc).__name__, "message": str(exc)}
            state = initial
        event = {
            "tool": tool,
            "args": args,
            "result": result,
            "started_at_unix": started,
            "ended_at_unix": time.time(),
            "approved_before_call": bool(
                approval
                and approval["decision"] == "approved"
                and approval["decided_at_unix"] <= started
            ),
            "business_records_changed": state["records"] != initial["records"],
        }
        self.db.execute("INSERT INTO journal(payload) VALUES (?)", (json.dumps(event),))
        self.db.commit()
        self.export()
        return result

    @staticmethod
    def checkout_quote(state, target):
        r, rule = state["records"], state["rules"]["checkout"]
        cart = r["carts"][target]
        subtotal = sum(
            r["products"][line["sku"]]["price_cents"] * line["quantity"] for line in cart["items"]
        )
        eligible = (
            cart["promotion"] == rule["promotion"] and subtotal >= rule["minimum_subtotal_cents"]
        )
        discount = subtotal * rule["discount_percent"] // 100 if eligible else 0
        shipping = rule["shipping_cents"]
        tax = (subtotal - discount + shipping) * rule["tax_percent"] // 100
        total = subtotal - discount + shipping + tax
        gift = min(total, r["gift_cards"][rule["gift_card"]]["balance_cents"])
        return {
            "quote_id": "quote-" + target,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "shipping_cents": shipping,
            "tax_cents": tax,
            "total_cents": total,
            "gift_cents": gift,
            "card_cents": total - gift,
        }

    @staticmethod
    def mutate(state, tool, target, data):
        r, rules = state["records"], state["rules"]
        if tool == "stock_reserve":
            cart = r["carts"][target]
            need(
                cart["status"] == "open" and target not in r["reservations"],
                "Cart unavailable or already reserved",
            )
            need(data["quote_id"] == "quote-" + target, "Quote mismatch")
            for line in cart["items"]:
                stock = r["stock"][line["sku"]]
                need(stock["available"] >= line["quantity"], "Insufficient stock")
                stock["available"] -= line["quantity"]
                stock["reserved"] += line["quantity"]
            r["reservations"][target] = {"items": cart["items"], "status": "reserved"}
            return {"reservation_id": target, "status": "reserved"}
        if tool == "stock_release":
            reservation = r["reservations"][target]
            need(
                reservation["status"] == "reserved" and "order-" + target not in r["orders"],
                "Reservation already allocated or released",
            )
            for line in reservation["items"]:
                stock = r["stock"][line["sku"]]
                stock["available"] += line["quantity"]
                stock["reserved"] -= line["quantity"]
            reservation["status"] = "released"
            return {"status": "released"}
        if tool == "payment_capture":
            quote = BusinessService.checkout_quote(state, target)
            need(
                target not in r["payments"] and r["reservations"][target]["status"] == "reserved",
                "Payment already exists or stock not reserved",
            )
            need(
                data["quote_id"] == quote["quote_id"]
                and data["gift_cents"] == quote["gift_cents"]
                and data["card_cents"] == quote["card_cents"],
                "Incorrect quote or payment allocation",
            )
            need(r["payment_methods"][data["card_id"]]["authorized"], "Unauthorized payment method")
            need(
                r["payment_methods"][data["card_id"]]["customer"] == r["carts"][target]["customer"],
                "Payment method belongs to another customer",
            )
            gift = r["gift_cards"][rules["checkout"]["gift_card"]]
            need(
                gift["customer"] == r["carts"][target]["customer"],
                "Gift card belongs to another customer",
            )
            gift["balance_cents"] -= data["gift_cents"]
            r["payments"][target] = {
                k: data[k] for k in ["gift_cents", "card_cents", "card_id"]
            } | {"status": "captured"}
            return {"payment_id": target, **r["payments"][target]}
        if tool == "payment_reverse":
            need(
                "order-" + target not in r["orders"]
                and r["payments"][target]["status"] == "captured",
                "Payment already committed or reversed",
            )
            payment = r["payments"][target]
            r["gift_cards"][rules["checkout"]["gift_card"]]["balance_cents"] += payment[
                "gift_cents"
            ]
            payment["status"] = "reversed"
            return {"status": "reversed"}
        if tool == "order_commit":
            need(
                "order-" + target not in r["orders"]
                and r["payments"][target]["status"] == "captured"
                and r["reservations"][target]["status"] == "reserved",
                "Paid reserved cart required; duplicate orders forbidden",
            )
            quote = BusinessService.checkout_quote(state, target)
            need(
                data["amount_cents"] == quote["total_cents"],
                "Approved order amount differs from quote",
            )
            # Gift balance is now debited; use the committed payment allocation for the original quote.
            payment = r["payments"][target]
            quote.update(gift_cents=payment["gift_cents"], card_cents=payment["card_cents"])
            need(data["quote_id"] == quote.pop("quote_id"), "Quote mismatch")
            for line in r["carts"][target]["items"]:
                r["stock"][line["sku"]]["reserved"] -= line["quantity"]
            r["reservations"][target]["status"] = "allocated"
            r["carts"][target]["status"] = "ordered"
            r["orders"]["order-" + target] = {
                "cart_id": target,
                "items": r["carts"][target]["items"],
                **quote,
                "status": "confirmed",
            }
            return {"order_id": "order-" + target, **r["orders"]["order-" + target]}
        if tool == "order_amend":
            order = r["orders"][target]
            need(
                order["status"] == "unshipped" and r["addresses"][data["address"]]["eligible"],
                "Ineligible order stage or address",
            )
            line = next(x for x in order["items"] if x["line_id"] == data["line_id"])
            new_stock = r["stock"][data["new_sku"]]
            need(new_stock["available"] >= line["quantity"], "Replacement stock unavailable")
            price = r["products"][data["new_sku"]]["price_cents"] * line["quantity"]
            difference = price - line["paid_cents"]
            need(
                data["additional_charge_cents"] == difference and difference >= 0,
                "Incorrect supported price difference",
            )
            old_stock = r["stock"][line["sku"]]
            old_stock["available"] += line["quantity"]
            old_stock["reserved"] -= line["quantity"]
            new_stock["available"] -= line["quantity"]
            new_stock["reserved"] += line["quantity"]
            line.update(sku=data["new_sku"], paid_cents=price)
            order.update(address=data["address"], total_cents=order["total_cents"] + difference)
            r["payments"][target]["captured_cents"] += difference
            return {"order_id": target, "additional_charge_cents": difference, "status": "modified"}
        if tool == "order_cancel":
            order, payment = r["orders"][target], r["payments"][target]
            need(
                data["amount_cents"] == payment["amount_cents"],
                "Approval must cover the actual reversal amount",
            )
            need(order["status"] == "unshipped", "Fulfillment cannot be cancelled")
            if payment["status"] == "captured":
                need(
                    data["financial_action"] == "refund" and not payment["refunded_cents"],
                    "Captured payment requires a nonduplicate refund",
                )
                payment["refunded_cents"] = payment["amount_cents"]
                r["refunds"]["cancel-" + target] = {
                    "order_id": target,
                    "amount_cents": payment["amount_cents"],
                }
            else:
                need(
                    payment["status"] == "authorized" and data["financial_action"] == "void",
                    "Authorization requires a void",
                )
                payment["status"] = "voided"
            stock = r["stock"][order["sku"]]
            stock["available"] += order["quantity"]
            stock["reserved"] -= order["quantity"]
            order["status"] = "cancelled"
            return {
                "order_id": target,
                "status": "cancelled",
                "amount_cents": payment["amount_cents"],
            }
        if tool == "delivery_investigate":
            need(r["packages"][target]["status"] == "missing", "Package is not missing")
            for key, item in r["cases"].items():
                if item.get("package") == target:
                    return {"investigation_id": key, "status": item["status"]}
            r["cases"]["investigation-" + target] = {
                "package": target,
                "status": "open",
                "carrier_reference": "carrier-" + target,
            }
            return {"investigation_id": "investigation-" + target, "status": "open"}
        if tool == "delivery_replace":
            package = r["packages"][target]
            need(
                package["status"] == "missing"
                and package["days_since_last_scan"] >= 7
                and "replacement" not in package,
                "Replacement not eligible or already created",
            )
            need(
                r["cases"][data["investigation_id"]]["package"] == target,
                "Investigation does not cover this package",
            )
            stock = r["stock"][package["sku"]]
            need(stock["available"] >= package["quantity"], "Replacement unavailable")
            stock["available"] -= package["quantity"]
            package["replacement"] = "replacement-" + target
            r["packages"][package["replacement"]] = {
                k: package[k] for k in ["order", "sku", "quantity"]
            } | {"status": "replacement_created", "replaces": target}
            return {"replacement_id": package["replacement"], "status": "replacement_created"}
        if tool in ["return_create", "exchange_create", "refund_issue"]:
            line, rule = r["lines"][target], rules["returns"]
            need(
                line["days_since_delivery"] <= rule["window_days"]
                and line["condition"] == rule["condition"],
                "Return ineligible",
            )
            quantity = data["quantity"]
            need(
                isinstance(quantity, int)
                and 0 < quantity <= line["quantity"] - line["refunded_quantity"],
                "Invalid remaining quantity",
            )
            if tool == "return_create":
                need(target not in r["returns"], "Return already exists")
                r["returns"][target] = {
                    "line_id": target,
                    "quantity": quantity,
                    "status": "accepted",
                }
            else:
                need(
                    r["returns"][target]["quantity"] == quantity
                    and r["returns"][target]["status"] == "accepted",
                    "Accepted return required",
                )
                if tool == "exchange_create":
                    need(target not in r["exchanges"], "Exchange already exists")
                    stock = r["stock"][data["new_sku"]]
                    need(stock["available"] >= quantity, "Replacement stock unavailable")
                    stock["available"] -= quantity
                    line["exchanged_to"] = data["new_sku"]
                    r["exchanges"][target] = {
                        "line_id": target,
                        "quantity": quantity,
                        "new_sku": data["new_sku"],
                        "status": "created",
                    }
                else:
                    payment = r["payments"][line["order"]]
                    total = line["paid_cents"] * quantity
                    card = total * payment["card_share_percent"] // 100
                    need(
                        target not in r["refunds"]
                        and data["amount_cents"] == total
                        and data["card_cents"] == card
                        and data["gift_cents"] == total - card,
                        "Incorrect or duplicate refund allocation",
                    )
                    r["refunds"][target] = {"line_id": target, **data}
                    payment["card_refunded_cents"] += card
                    payment["gift_refunded_cents"] += total - card
                    line["refunded_quantity"] += quantity
                if r["exchanges"] and r["refunds"]:
                    for case in r["cases"].values():
                        if case.get("order") == line["order"]:
                            case["status"] = "resolved"
            return {
                "record_id": target,
                "status": "accepted" if tool == "return_create" else "created",
            }
        if tool == "warranty_book":
            purchase, diagnostics, rule = (
                r["purchases"][target],
                r["diagnostics"][target],
                rules["warranty"],
            )
            need(
                purchase["serial"] == data["serial"]
                and purchase["age_days"] <= rule["coverage_days"],
                "Serial or warranty mismatch",
            )
            need(
                diagnostics["fault"] in rule["covered_faults"]
                and all(diagnostics.get(k) for k in rule["required_checks"]),
                "Required diagnostic evidence missing or fault not covered",
            )
            need(
                target not in r["claims"] and r["service_slots"][data["slot"]]["available"],
                "Claim duplicate or slot unavailable",
            )
            slot = r["service_slots"][data["slot"]]
            slot["available"] = False
            r["claims"][target] = {
                "serial": data["serial"],
                "status": "service_booked",
                "coverage": "warranty",
            }
            r["bookings"][target] = {
                "slot": data["slot"],
                "provider": slot["provider"],
                "fee_cents": rule["covered_service_fee_cents"],
            }
            return {"claim_id": target, **r["bookings"][target]}
        if tool == "loyalty_adjust":
            purchase, rule = r["purchases"][target], rules["loyalty"]
            need(
                purchase["captured"]
                and purchase["age_days"] > rule["posting_delay_days"]
                and target not in r["adjustments"],
                "Purchase pending, unpaid or already corrected",
            )
            posted = sum(
                item["points"] for item in r["points_ledger"].values() if item["purchase"] == target
            )
            expected = purchase["eligible_cents"] // rule["cents_per_point"]
            need(
                data["points"] == expected - posted and data["points"] != 0,
                "Incorrect ledger correction",
            )
            r["points_ledger"]["adjust-" + target] = {"purchase": target, "points": data["points"]}
            r["adjustments"][target] = data
            r["accounts"][purchase["account"]]["balance"] += data["points"]
            return {
                "adjustment_id": target,
                "balance": r["accounts"][purchase["account"]]["balance"],
            }
        if tool == "subscription_update":
            subscription, rule = r["subscriptions"][target], rules["subscription"]
            need(
                data["cycle_charge_cents"]
                == subscription["unit_cents"]
                * data["quantity"]
                * (100 - subscription["discount_percent"])
                // 100,
                "Approval must cover the revised cycle charge",
            )
            skip, effective, quantity = (
                data["skip_cycle"],
                data["effective_cycle"],
                data["quantity"],
            )
            cycles = subscription["cycles"]
            need(
                not cycles[skip]["cutoff_passed"] and cycles[skip]["status"] == "scheduled",
                "Skip cutoff passed or already skipped",
            )
            need(
                rule["discount_minimum_quantity"] <= quantity <= rule["quantity_maximum"],
                "Quantity changes discount eligibility or exceeds stock rule; further customer consent required",
            )
            need(
                cycles[effective]["day"] > cycles[skip]["day"],
                "Quantity change starts on the wrong cycle",
            )
            cycles[skip].update(status="skipped", charge_cents=0)
            for cycle in cycles.values():
                if cycle["day"] >= cycles[effective]["day"]:
                    need(not cycle["cutoff_passed"], "Quantity cutoff passed")
                    cycle.update(
                        quantity=quantity,
                        charge_cents=subscription["unit_cents"]
                        * quantity
                        * (100 - subscription["discount_percent"])
                        // 100,
                    )
            subscription["future_quantity"] = quantity
            return {
                "subscription_id": target,
                "status": "updated",
                "next_delivery_day": cycles[effective]["day"],
            }
        if tool == "purchase_order_create":
            supplier, rule = r["suppliers"][target], rules["replenishment"]
            need(
                "po-" + target not in r["purchase_orders"]
                and data["arrival_day"] == supplier["lead_days"],
                "Duplicate purchase or incorrect arrival",
            )
            need(
                data["amount_cents"] <= rule["budget_cents"] and data["lines"],
                "Budget exceeded or empty order",
            )
            total = 0
            seen = set()
            for line in data["lines"]:
                sku, quantity = line["sku"], line["quantity"]
                need(sku not in seen, "Duplicate purchase-order line")
                seen.add(sku)
                item = supplier["items"][sku]
                need(
                    quantity >= item["minimum"] and quantity % item["pack"] == 0,
                    "Minimum or pack quantity violated",
                )
                stock, demand = r["stock"][sku], r["demand"][sku]["units_per_day"]
                free = stock["on_hand"] - stock["reserved"]
                inbound = [x for x in r["inbound"].values() if x["sku"] == sku]
                next_day = min(x["day"] for x in inbound)
                need(
                    free < demand * next_day and free >= demand * supplier["lead_days"],
                    "Not at risk before inbound or supplier arrives after stockout",
                )
                projected = (
                    free
                    + sum(x["quantity"] for x in inbound if x["day"] <= rule["horizon_days"])
                    - demand * rule["horizon_days"]
                )
                needed = max(item["minimum"], rule["target_units"] - projected)
                needed = ((needed + item["pack"] - 1) // item["pack"]) * item["pack"]
                need(quantity == needed, "Quantity does not follow the prescribed projection")
                total += quantity * item["unit_cents"]
            need(total == data["amount_cents"], "Incorrect purchase amount")
            r["purchase_orders"]["po-" + target] = {"supplier": target, **data, "status": "ordered"}
            return {"purchase_order_id": "po-" + target, **r["purchase_orders"]["po-" + target]}
        if tool in ["recall_quarantine", "recall_notify"]:
            notice = r["recalls"][target]
            if tool == "recall_quarantine":
                for stock_id in data["stock_ids"]:
                    stock = r["stock_lots"][stock_id]
                    need(
                        stock["sku"] == notice["sku"] and stock["lot"] == notice["lot"],
                        "Stock outside recall scope",
                    )
                    stock["status"] = "quarantined"
            else:
                for purchase_id in data["purchase_ids"]:
                    purchase = r["purchases"][purchase_id]
                    need(
                        purchase["sku"] == notice["sku"] and purchase["lot"] == notice["lot"],
                        "Purchase outside recall scope",
                    )
                    key = target + "-" + purchase_id
                    r["cases"].setdefault(
                        key, {"recall": target, "purchase": purchase_id, "status": "open"}
                    )
                    r["notifications"].setdefault(
                        key,
                        {
                            "recall": target,
                            "purchase": purchase_id,
                            "destination": purchase["contact"],
                            "status": "enqueued",
                        },
                    )
            return {
                "recall_id": target,
                "status": "quarantined" if tool == "recall_quarantine" else "enqueued",
            }
        if tool == "reconciliation_record":
            need(target not in r["reports"], "Reconciliation already recorded")
            # The report API stores the agent's explanation; independent grading checks it.
            r["reports"][target] = data
            return {"report_id": target, "status": "recorded"}
        raise ValueError("Unknown operation")


def object_schema(properties):
    return {
        "type": "object",
        "properties": {
            key: {"type": "string", "description": value} for key, value in properties.items()
        },
        "required": list(properties),
        "additionalProperties": False,
    }


def catalog():
    rows = [
        ("policy_get", "Read the current scenario's supplied business rules.", {}),
        (
            "permissions_get",
            "Read action scope, amount ceilings and native approval requirements.",
            {},
        ),
        (
            "records_read",
            "Retrieve one authoritative business record.",
            {"collection": "Collection name", "record_id": "Record identifier"},
        ),
        (
            "records_search",
            "List records in a named collection, optionally filtered by exact top-level field equality. Empty filters_json {} lists all records.",
            {"collection": "Collection name", "filters_json": "JSON object of field/value filters"},
        ),
        (
            "checkout_quote",
            "Quote discounts, shipping, tax and original gift/card allocation without a purchase.",
            {"target": "Cart identifier"},
        ),
    ]
    rows += [
        (
            name,
            description
            + " Obtain native approval before invoking this action; all money is integer cents.",
            {
                "target": "Business record identifier",
                "data_json": "JSON object with the fields documented for this tool",
                "approval_id": "Approval identifier returned by request_action_approval",
                "idempotency_key": "Stable unique key for this exact operation",
            },
        )
        for name, description in WRITES.items()
    ]
    return [
        {"name": name, "description": description, "inputSchema": object_schema(properties)}
        for name, description, properties in rows
    ]


async def serve(directory):
    service = BusinessService(directory)

    async def list_tools(context, params):
        return types.ListToolsResult(tools=[types.Tool(**item) for item in catalog()])

    async def call_tool(context, params):
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(service.invoke(params.name, params.arguments or {})),
                )
            ]
        )

    server = Server("retail-workflows", on_list_tools=list_tools, on_call_tool=call_tool)

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["initialize", "serve"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.mode == "initialize":
        BusinessService.initialize(
            args.directory, json.loads((args.directory.parent / "initial.json").read_text())
        )
    else:
        asyncio.run(serve(args.directory))


if __name__ == "__main__":
    main()
