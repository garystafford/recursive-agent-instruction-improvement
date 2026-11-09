const frozen = require('./business-rules.cjs');

Object.assign(exports, frozen);
exports.reporting = (output, context) => {
  const evidence = context.providerResponse.metadata.evidence;
  const final = JSON.parse(output);
  for (const item of final.results || []) {
    if (item.outcome !== 'skipped') continue;
    const parts = item.target.split('/');
    if (parts.length !== 2) continue;
    const [subscriptionId, cycleId] = parts;
    const cycle = evidence.state.records.subscriptions?.[subscriptionId]?.cycles?.[cycleId];
    // Resolve a qualified identifier only when it names a real, skipped cycle.
    if (cycle?.status === 'skipped' && cycle.charge_cents === 0) item.target = cycleId;
  }
  return frozen.reporting(JSON.stringify(final), context);
};
