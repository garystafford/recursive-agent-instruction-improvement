"""Twelve families with separately worded development and held-out conversations."""

from refund_pilot.retail.contracts import Case, Expected, Line, Tender

FAMILIES = [
    "mixed_request",
    "ambiguous_item",
    "changed_size",
    "unavailable_size",
    "split_tender",
    "multiple_orders",
    "different_windows",
    "exchange_only",
    "jewelry_inspection",
    "final_sale",
    "policy_version",
    "combined",
]

# The fictional store's complete rules, not a claim about any individual retailer.
POLICIES = {
    "apparel": {"window_days": 30, "condition": "original", "exchange": True},
    "electronics": {"window_days": 15, "condition": "original", "exchange": True},
    "software": {"window_days": 30, "opened": "exchange_only_same_title", "exchange": True},
    "jewelry": {
        "window_days": 30,
        "inspection_required": True,
        "altered": "final_sale",
        "exchange": False,
    },
}


def policies(category: str, version: str) -> dict:
    if version not in {"v1", "v2"}:
        return {"error": "unknown_policy_version"}
    result = {**POLICIES[category]}
    if version == "v2" and category == "electronics":
        result["window_days"] = 10
    return {
        "policy_id": f"{category}-{version}",
        "version": version,
        **result,
        "rules": "Inclusive day boundary. Refund requires received goods; jewelry also requires approved inspection. Altered jewelry is final sale for change of mind. Exchanges use the same product and original price. Original condition and tags/accessories are required unless an explicit opened-software exception applies. Quotes calculate amounts but do not decide policy eligibility.",
    }


def fixtures(split: str) -> list[Case]:
    held = split == "heldout"
    cases = []
    for family, name in enumerate(FAMILIES, 1):
        prefix = f"{'H' if held else 'D'}{family:02}"
        order1, order2 = f"{prefix}-A", f"{prefix}-B"
        price = 4937 + family * 113 + (257 if held else 0)

        def line(
            suffix,
            description,
            category="apparel",
            prefix=prefix,
            order1=order1,
            price=price,
            **updates,
        ):
            return Line(
                line_id=f"{prefix}-{suffix}",
                order_id=order1,
                description=description,
                category=category,
                policy_version="v1",
                days_since_delivery=12,
                condition="original",
                unit_paid_cents=price,
                quantity=1,
                refunded_quantity=0,
                inspection="approved",
                received=True,
                variants=["medium", "large"],
            ).model_copy(update=updates)

        jacket = line("J", "navy rain jacket" if held else "blue jacket")
        shoes = line("S", "walking shoes" if held else "running shoes", order_id=order2)
        keep = line("K", "charcoal jacket" if held else "black jacket")
        lines = [jacket, shoes, keep]
        expected = [
            Expected(
                line_id=jacket.line_id,
                action="exchange",
                quantity=1,
                variant="medium",
                refund_cents=0,
            ),
            Expected(
                line_id=shoes.line_id, action="refund", quantity=1, variant="", refund_cents=price
            ),
            Expected(line_id=keep.line_id, action="keep", quantity=0, variant="", refund_cents=0),
        ]
        initial = (
            f"Please swap my {jacket.description} for medium and return the {shoes.description} for a refund. Keep the {keep.description} unchanged."
            if held
            else f"Exchange the {jacket.description} for medium, refund the {shoes.description}, and leave the {keep.description} alone."
        )
        clarification = "All goods are already received by the return center. Refer to the order records for condition and inspection."
        revision = ""
        if family == 2:
            duplicate = line("J2", jacket.description, order_id=order2)
            lines.append(duplicate)
            initial = f"Exchange my {jacket.description} for medium. Refund the {shoes.description}. Leave the {keep.description} alone."
            clarification += f" The jacket I mean is on order {order1}, line {jacket.line_id}; leave the matching jacket on {order2} unchanged."
        if family in {3, 4, 12}:
            revision = (
                "Change only the exchange: large instead of medium. If large is unavailable, keep that item. Everything else stays as requested."
                if held
                else "Actually make the jacket large. If large is unavailable, keep it; do not refund it. All other instructions stay the same."
            )
            expected[0] = expected[0].model_copy(update={"variant": "large"})
        if family == 4:
            jacket.variants = ["medium"]
            expected[0] = expected[0].model_copy(
                update={"action": "keep", "quantity": 0, "variant": ""}
            )
        if family == 6:
            shoes.quantity = 2
            shoes.refunded_quantity = 1
            initial += (
                " I already returned one pair from the shoe order; refund only the remaining pair."
            )
        if family in {7, 8, 11, 12}:
            electronics = line(
                "E",
                "wireless headphones" if held else "headphones",
                "electronics",
                days_since_delivery=18 if family in {7, 12} else 15,
            )
            lines.append(electronics)
            initial += f" Also refund the {electronics.description}, if eligible."
            action = "deny" if family in {7, 12} else "refund"
            if family == 11:
                electronics.policy_version = "v2"
                electronics.days_since_delivery = 11
                action = "deny"
                older = line("E1", "wired headphones", "electronics", days_since_delivery=15)
                lines.append(older)
                initial += " Also refund the wired headphones if eligible."
                expected.append(
                    Expected(
                        line_id=older.line_id,
                        action="refund",
                        quantity=1,
                        variant="",
                        refund_cents=price,
                    )
                )
            expected.append(
                Expected(
                    line_id=electronics.line_id,
                    action=action,
                    quantity=1,
                    variant="",
                    refund_cents=price if action == "refund" else 0,
                )
            )
        if family == 8:
            software = line(
                "G",
                "opened puzzle game",
                "software",
                condition="opened",
                variants=["same-title-PC", "same-title-console"],
            )
            lines.append(software)
            initial += " I would prefer a refund for the opened puzzle game, but authorize a same-title-PC exchange if a refund isn't allowed."
            expected.append(
                Expected(
                    line_id=software.line_id,
                    action="exchange",
                    quantity=1,
                    variant="same-title-PC",
                    refund_cents=0,
                )
            )
        if family in {9, 10, 12}:
            ring = line(
                "R",
                "silver ring" if held else "gold ring",
                "jewelry",
                inspection="pending" if family in {9, 12} else "approved",
                condition="altered" if family == 10 else "original",
            )
            lines.append(ring)
            initial += f" I also want to return the {ring.description} for a refund if eligible."
            action = "deny" if family == 10 else ("waiting" if family == 12 else "refund")
            expected.append(
                Expected(
                    line_id=ring.line_id,
                    action=action,
                    quantity=1,
                    variant="",
                    refund_cents=price if action == "refund" else 0,
                )
            )
        if family in {5, 6, 12}:
            initial += " Please put any gift-credit portion of the refund onto my bank card if you can; if policy doesn't allow that, use the required original methods."
        tenders = {}
        for order in {x.order_id for x in lines}:
            total = sum(x.unit_paid_cents * x.quantity for x in lines if x.order_id == order)
            previous = sum(
                x.unit_paid_cents * x.refunded_quantity for x in lines if x.order_id == order
            )
            gift = total // 3 if family in {5, 6, 12} else 0
            amounts = [("card", total - gift), ("gift_credit", gift)] if gift else [("card", total)]
            # Cumulative round-half-up allocation; final tender receives the remainder.
            prev_first = (previous * amounts[0][1] * 2 + total) // (2 * total)
            tenders[order] = [
                Tender(
                    tender_id=f"{order}-{kind}",
                    kind=kind,
                    captured_cents=amount,
                    refunded_cents=prev_first if i == 0 else previous - prev_first,
                )
                for i, (kind, amount) in enumerate(amounts)
            ]
        cases.append(
            Case(
                name=f"{split}-{name}",
                family=family,
                split=split,
                customer_id=f"{prefix}-customer",
                lines=lines,
                tenders=tenders,
                initial_message=initial,
                clarification=clarification,
                revision=revision,
                inspection_event=family == 9,
                expected=expected,
            )
        )
    return cases
