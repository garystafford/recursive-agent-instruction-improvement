# Retail workflow study specification

This study defines twelve distinct retail task types for the [cumulative instruction-improvement protocol](cumulative-instruction-improvement-protocol.md). One retail operations agent uses the same shared instructions and tool catalog across all tasks. Each task supplies its own request, business data, permissions, and applicable rules. Instruction revisions apply to the shared instructions, rather than creating separate instructions for each task.

The task catalog and success requirements are specified below. Tool descriptions are required capabilities, not verified API names or claims that those tools already exist. Map existing tools to these capabilities and implement missing capabilities before baseline qualification. Transactions, customer communications, and supplier actions use simulated services.

## Task catalog

| ID | Task | Primary result |
| --- | --- | --- |
| T01 | Product selection | A supported recommendation meeting the customer's constraints |
| T02 | Purchase and checkout | An authorized order with correct pricing, payment, and stock allocation |
| T03 | Modify an existing order | Permitted changes to an existing order |
| T04 | Cancel an order | Eligible fulfillment stopped and financial and stock effects reversed correctly |
| T05 | Resolve a delivery exception | A missing shipment investigated or replaced under the applicable rules |
| T06 | Process a return and exchange | Correct item-level return, exchange, and refund outcomes |
| T07 | Arrange warranty service | A supported warranty decision and the required service arrangement |
| T08 | Correct a loyalty account | An accurate points ledger with supported corrections |
| T09 | Manage a recurring subscription | Correct changes to specified delivery and billing cycles |
| T10 | Plan inventory replenishment | A justified replenishment order or purchasing approval request |
| T11 | Handle a product recall | Affected stock blocked and required follow-up initiated |
| T12 | Reconcile payment settlement | An explained payout reconciliation with unresolved exceptions identified |

## Requirements shared by all tasks

- Provide the agent with the business rules and evidence needed to complete each task. Success must not depend on undisclosed business requirements.
- Use a fresh session, sandbox, and independent starting state for each run, as defined in the protocol. Match starting data between compared instruction versions.
- Make shared tools available for reading applicable policies, checking permissions and approval status, and retrieving relevant customer or business records. Enforce the supplied permissions in the services.
- For actions requiring approval, use the protocol's automated native approval mechanism. Approval must cover the action, target, and amount where applicable, and precede the committed action.
- Retain initial and final business state, action records, tool arguments and results, approval events, and final outputs for Promptfoo evaluation.
- Check business correctness, authorization, and truthful reporting independently of time and cost. A correct final answer does not substitute for a required business action.
- Accept different valid plans or recommendations when they satisfy the declared requirements. Require a particular action order only where policy or a business dependency requires it.
- An escalation or refusal passes only when the task's rules and evidence require that outcome. Unnecessary escalation does not count as successful completion.
- Check that unrelated records remain unchanged, unauthorized actions do not occur, and repeated handling does not produce duplicate business effects.

## T01: Product selection

**Request:** "Find a waterproof hiking jacket within my budget, available in my size before Friday."

**Required tools:** Read or search the product catalog, specifications, prices, available sizes, stock by fulfillment location, applicable promotions, and delivery estimates. Retrieve stated customer preferences where needed. This task requires no order or payment write tools.

**Success checks:**

- Every recommended product satisfies all mandatory requirements supported by the case: product attributes, size, total-price basis, availability, and delivery deadline.
- Distinguish mandatory requirements from preferences and explain material tradeoffs using retrieved facts.
- If multiple products qualify, accept any recommendation consistent with the declared selection criteria.
- If no product qualifies, identify the unmet requirements and present alternatives only with their limitations stated.
- Do not create an order, charge a payment method, or change inventory.

## T02: Purchase and checkout

**Request:** "Buy these items, apply my eligible promotion, and use my gift card before charging the balance."

**Required tools:** Read the cart, catalog, stock, promotion eligibility, shipping options, tax rules, gift-card balance, and available payment methods. Obtain a price quote, reserve stock, apply permitted gift-card funds, authorize or capture the remaining payment, and commit the order. Support releasing reservations and reversing incomplete payment operations when required by checkout rules.

**Success checks:**

- Order the requested products and quantities using an eligible fulfillment option.
- Calculate discounts, shipping, tax, and total correctly under the supplied pricing rules.
- Apply gift-card funds in the requested order and charge only the correct remaining balance to an authorized payment method.
- Commit the purchase only after required approval; create exactly one order and the corresponding payment and stock effects.
- Handle stock or payment failure according to the declared rules, without leaving an unsupported charge, order, or reservation.
- Report the actual order status and payment allocation accurately.

## T03: Modify an existing order

**Request:** "Change the size of one item and update the delivery address before dispatch."

**Required tools:** Read the order, fulfillment status, catalog variants, stock, shipping eligibility, pricing, and amendment rules. Replace an eligible order line, change the permitted delivery address, adjust reservations, and handle any authorized payment difference.

**Success checks:**

- Establish which requested changes are permitted at the recorded fulfillment stage.
- Select the requested replacement variant and validate availability and delivery eligibility for the new address.
- Recalculate affected prices, shipping, tax, and payment differences under the amendment rules.
- Obtain any approval required for the revised purchase amount or other protected change before committing it.
- Update only the eligible requested fields and associated stock and payment records; preserve unrelated lines and shipped contents.
- Explain any requested change that could not be made and report the committed result accurately.

## T04: Cancel an order

**Request:** "Cancel my order if it has not shipped."

**Required tools:** Read order and shipment status, payment state, stock reservations, and cancellation rules. Cancel eligible fulfillment, release reservations, void an authorization or issue the permitted refund, and update the order status.

**Success checks:**

- Determine eligibility from the actual order and shipment records.
- For an eligible order, stop fulfillment and apply the required stock and payment reversals.
- Distinguish an uncaptured authorization from a captured payment when choosing the financial action.
- For an ineligible order, leave protected fulfillment and payment records unchanged and explain the applicable next step.
- Do not duplicate refunds, reversals, or stock releases.
- Ensure the final order, payment, and inventory records agree with the reported outcome.

## T05: Resolve a delivery exception

**Request:** "My order arrived in two packages, but the second package is missing."

**Required tools:** Read the order-to-package mapping, shipment contents, carrier events, delivery evidence, existing support cases, and delivery-exception policy. Open a carrier investigation, create or update a support case, and authorize a replacement shipment when the supplied rules allow it.

**Success checks:**

- Identify the affected package and its contents without treating the entire order as missing.
- Reconcile carrier events with the case's date and delivery evidence.
- Take the policy-supported action: investigation, permitted replacement, or a clearly explained pending outcome.
- Avoid duplicate investigations or replacements when an existing action already covers the missing package.
- Preserve delivered items and unrelated shipments, payments, and stock.
- State what has actually been initiated and what remains unresolved; do not report delivery or replacement completion without evidence.

## T06: Process a return and exchange

**Request:** "Exchange the jacket for another size and refund the shoes."

**Required tools:** Read purchase history, line-level prices, original payment allocation, delivery dates, item condition or inspection records, return policies, stock, and previous returns. Create eligible returns and exchanges, reserve replacement stock, obtain required approvals, issue refunds, and update order and support records.

**Success checks:**

- Resolve each requested action to the correct purchased item and quantity.
- Apply item-specific eligibility, inspection, deadline, and exclusion rules.
- Create the requested eligible exchange and allocate the correct replacement stock.
- Calculate the permitted refund from the original transaction and use the required original payment allocation.
- Obtain required approval before each protected business action.
- Leave ineligible or unrelated items unchanged and prevent duplicate returns, exchanges, or refunds.
- Report the distinct outcome for each requested item accurately.

## T07: Arrange warranty service

**Request:** "My appliance stopped working after the return window. Can you arrange a repair?"

**Required tools:** Read the purchase, product or serial number, warranty terms, coverage dates, supplied fault information, required diagnostic questions, prior claims, and service options. Gather missing required information and create the permitted warranty claim, service booking, or escalation case.

**Success checks:**

- Match the claimed product to the purchase and relevant warranty terms.
- Distinguish warranty eligibility from ordinary return eligibility.
- Collect required information and follow the supplied diagnostic or routing rules without inventing diagnostic findings.
- Create the correct authorized service arrangement when eligible; otherwise explain the supported coverage decision and permitted next step.
- Preserve existing claims and avoid duplicate service arrangements.
- Do not promise unsupported coverage, waive an unauthorized charge, or substitute an unrequested refund for the required service workflow.

## T08: Correct a loyalty account

**Request:** "The points from my recent purchase are missing, and one transaction appears twice."

**Required tools:** Read the loyalty account, order and payment history, points ledger, earning rules, posting delays, expiration rules, and prior adjustments. Post authorized ledger corrections linked to supporting transactions and create an investigation case when evidence is insufficient.

**Success checks:**

- Reconcile the disputed entries to the relevant qualifying purchases and existing ledger activity.
- Distinguish legitimately pending points from missing points and duplicate credits from valid separate earnings.
- Calculate any required correction under the supplied earning and adjustment rules.
- Link every adjustment to its supporting transaction and obtain required authorization.
- Preserve valid entries and produce the correct resulting balance without duplicate correction entries.
- Explain unresolved discrepancies without inventing purchase or payment evidence.

## T09: Manage a recurring subscription

**Request:** "Skip my next delivery, change the quantity for future deliveries, and keep my discount."

**Required tools:** Read the subscription, upcoming delivery and billing schedule, cutoff times, price and discount eligibility, stock constraints, and existing pending changes. Skip an eligible cycle, update future quantities, recalculate affected billing, and persist the revised schedule.

**Success checks:**

- Apply the skip to the intended eligible delivery and billing cycle.
- Apply the quantity change from the requested effective cycle, respecting cutoff rules.
- Preserve the discount when the supplied eligibility rules allow it; otherwise disclose the consequence and obtain any required confirmation before committing the affected change.
- Keep delivery dates, quantities, charges, and subscription status consistent.
- Preserve unaffected cycles and prevent duplicate shipments or charges for the skipped cycle.
- Report the next actual delivery and billing arrangements accurately.

## T10: Plan inventory replenishment

**Request:** "Prepare a replenishment order for products likely to run out before the next supplier delivery."

**Required tools:** Read stock on hand, reservations, sales or demand history, existing inbound orders, supplier catalogs, lead times, minimum order quantities, case-pack sizes, budgets, and purchasing rules. Calculate the prescribed demand and stock projections and create a permitted purchase order or purchasing approval request.

**Success checks:**

- Calculate projected available stock over the specified horizon using the declared demand rule, reservations, and scheduled inbound deliveries.
- Identify products requiring replenishment using the supplied stock or service targets.
- Choose quantities and suppliers consistent with lead times, minimum quantities, pack sizes, budget, and authorization rules.
- Avoid duplicate procurement for demand already covered by a suitable inbound order.
- Create the required purchase order or approval request with correct lines, quantities, amounts, and expected dates.
- Keep goods on order separate from received, sellable inventory.
- Accept alternative purchasing plans when they satisfy the declared constraints and selection rules.

## T11: Handle a product recall

**Request:** "Process this recall notice for the affected product batch."

**Required tools:** Read the supplied recall notice, product and lot identifiers, inventory by location, lot-linked purchases and shipments, existing recall actions, and the specified recall procedure. Block sale or quarantine affected stock, create the required service cases, and enqueue the required simulated customer notifications.

**Success checks:**

- Determine the affected products, batches, stock locations, and purchases from the supplied notice and traceability records.
- Block further sale or quarantine the affected available stock according to the specified procedure.
- Create the required cases and notification records for affected customers with supported content and destinations.
- Preserve unaffected products, batches, customers, and stock.
- Avoid duplicate cases or notifications for recall actions already completed.
- Report traceability gaps or incomplete actions rather than declaring the recall fully processed without supporting records.

## T12: Reconcile payment settlement

**Request:** "Explain why yesterday's processor payout does not match our sales records."

**Required tools:** Read order totals, authorizations and captured payments, refunds, chargebacks, fees, processor settlement entries, payout records, currencies, and settlement cutoff rules. Produce a reconciliation report and record supported unresolved exceptions. This task requires no payment or inventory mutation.

**Success checks:**

- Select the correct payout, currency, and settlement period using the supplied cutoff rules.
- Match transactions between sales, payment, and processor records without counting authorizations as captured sales or counting entries twice.
- Calculate the payout reconciliation using the actual settled charges, refunds, chargebacks, fees, and adjustments.
- Separate explained timing differences from genuine unmatched or inconsistent records.
- Account for the observed difference, with any remaining amount explicitly linked to unresolved exceptions.
- Support explanations with transaction references and preserve source financial records; do not create charges, refunds, or balancing entries to force agreement.

## Case design and execution schedule

Each task type needs its own development and evaluation cases, expected business outcomes, permitted alternative outcomes, and prohibited actions. Fresh identifiers or prices create new cases within a task type; they do not create additional task types.

Promptfoo checks must evaluate the case's declared requirements against outputs, action traces, approvals, and final state. Validate the checks against known correct and incorrect outcomes before baseline qualification. Do not enforce a single reference tool sequence when several sequences produce valid outcomes.

The following study choices remain unspecified:

- Concrete case data and development/evaluation assignments for each task.
- Development cases per task and improvement round.
- Improvement-round count and evaluation repetitions.
- Comparison schedule, execution order, and checkpoint boundaries.
- Total task executions and instruction-generation calls derived from that schedule.
- Cost estimate and execution authorization for the resulting schedule.

Models, reasoning settings, hosted execution, cumulative feedback, Promptfoo evaluation, measurement boundaries, and percentage tolerances remain defined by the general protocol.
