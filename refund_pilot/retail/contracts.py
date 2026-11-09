"""Pydantic contracts for fixtures, dialogue and model-facing tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tender(Contract):
    tender_id: str
    kind: Literal["card", "gift_credit"]
    captured_cents: int = Field(gt=0)
    refunded_cents: int = Field(ge=0)


class Line(Contract):
    line_id: str
    order_id: str
    description: str
    category: Literal["apparel", "electronics", "software", "jewelry"]
    policy_version: str
    days_since_delivery: int = Field(ge=0)
    condition: Literal["original", "opened", "altered"]
    unit_paid_cents: int = Field(gt=0)
    quantity: int = Field(gt=0)
    refunded_quantity: int = Field(ge=0)
    inspection: Literal["approved", "pending"]
    received: bool
    variants: list[str]


class ItemDecision(Contract):
    line_id: str
    action: Literal["refund", "exchange", "keep", "deny", "waiting"]
    quantity: int = Field(ge=0)
    variant: str
    policy_id: str
    reason: str
    refund_cents: int = Field(ge=0)


class WorkerTurn(Contract):
    phase: Literal["clarify", "review", "complete"]
    message: str
    questions: list[str]
    items: list[ItemDecision]


class Expected(Contract):
    line_id: str
    action: Literal["refund", "exchange", "keep", "deny", "waiting"]
    quantity: int
    variant: str
    refund_cents: int


class Case(Contract):
    name: str
    family: int
    split: Literal["development", "heldout"]
    customer_id: str
    lines: list[Line]
    tenders: dict[str, list[Tender]]
    initial_message: str
    clarification: str
    revision: str
    inspection_event: bool
    expected: list[Expected]


class Empty(Contract):
    pass


class LineLookup(Contract):
    line_id: str


class PolicyLookup(Contract):
    category: Literal["apparel", "electronics", "software", "jewelry"]
    version: str


class RefundQuote(Contract):
    line_id: str
    quantity: int = Field(gt=0)


class IssueRefund(Contract):
    quote_id: str
    operation_key: str


class Exchange(Contract):
    line_id: str
    quantity: int = Field(gt=0)
    variant: str
    operation_key: str


TOOLS = {
    "orders_list": ("orders", Empty),
    "orders_get_line": ("orders", LineLookup),
    "policy_get": ("policy", PolicyLookup),
    "inventory_get_variants": ("inventory", LineLookup),
    "inventory_get_receipt": ("inventory", LineLookup),
    "inventory_create_exchange": ("inventory", Exchange),
    "payments_get_state": ("payments", Empty),
    "payments_quote_refund": ("payments", RefundQuote),
    "payments_issue_refund": ("payments", IssueRefund),
    "support_get_conversation": ("support", Empty),
}
