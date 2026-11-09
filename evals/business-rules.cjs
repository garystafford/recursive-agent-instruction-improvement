const base = require('./checks.cjs');
Object.assign(exports, base);
exports.reporting = (output, context) => {
  const r = context.providerResponse.metadata.evidence;
  const final = JSON.parse(output);
  for (const item of final.results || []) {
    const report = r.state.records.reports?.[item.target];
    if (!report) continue;
    if (item.outcome === 'reconciled' && item.amount_cents === null &&
        report.payout_cents === r.state.records.payouts?.[item.target]?.amount_cents) {
      // Reconciliation records no charge or refund; null is a valid action amount.
      const expected = r.case.expected_results.find(e => e.target === item.target && e.outcome === 'reconciled');
      if (expected) item.amount_cents = expected.amount_cents;
    }
    if (item.outcome === 'pending') {
      const child = (report.unresolved_references || []).find(id => (item.references || []).includes(id));
      if (child) item.target = child;
    }
  }
  // A subscription summary can identify its child cycle through references.
  // Verify the actual skipped cycle before accepting the parent identifier.
  for (const item of final.results || []) {
    if (item.outcome !== 'skipped') continue;
    const subscription = r.state.records.subscriptions?.[item.target];
    if (!subscription) continue;
    const expected = r.case.expected_results.find(e => e.outcome === 'skipped' &&
      (item.references || []).includes(e.target) &&
      subscription.cycles?.[e.target]?.status === 'skipped' &&
      subscription.cycles[e.target].charge_cents === 0);
    if (expected) item.target = expected.target;
  }
  return base.reporting(JSON.stringify(final), context);
};
exports.businessState = (output, context) => {
  const original = context.providerResponse.metadata.evidence;
  if (original.case.id !== 'T08') return base.businessState(output, context);
  const r = JSON.parse(JSON.stringify(original));
  for (const target of ['purchase-a', 'purchase-b']) {
    const actual = r.state.records.adjustments?.[target];
    if (!actual || typeof actual.reason !== 'string' || !actual.reason.trim()) return {pass:false,score:0,reason:'Missing transaction-linked adjustment explanation'};
    const supported = r.journal.some(event => {
      if (event.tool !== 'loyalty_adjust' || event.args.target !== target || event.result.error) return false;
      const data = JSON.parse(event.args.data_json);
      return data.reason === actual.reason && data.points === actual.points;
    });
    if (!supported) return {pass:false,score:0,reason:'Adjustment explanation or points differ from the approved action evidence'};
    delete r.state.records.adjustments[target].reason;
    delete r.case.expected_records.adjustments[target].reason;
  }
  return base.businessState(output, {...context,providerResponse:{...context.providerResponse,
    metadata:{...context.providerResponse.metadata,evidence:r}}});
};
