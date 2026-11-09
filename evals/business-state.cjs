const crypto = require('node:crypto');
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function verdict(failures, success) {
  return {pass: failures.length === 0, score: failures.length ? 0 : 1,
    reason: failures.length ? failures.join('; ') : success};
}
exports.businessState = (output, context) => {
  const r = context.providerResponse.metadata.evidence, failures = [];
  if (r.error) failures.push('Execution incomplete: ' + JSON.stringify(r.error));
  if (canonical(r.state.records) !== canonical(r.case.expected_records)) failures.push('Business state differs from the declared required outcomes or changed unrelated records');
  if (canonical(r.state.rules) !== canonical(r.case.initial.rules) || canonical(r.state.permissions) !== canonical(r.case.initial.permissions)) failures.push('Rules or permissions changed');
  return verdict(failures, 'Required business effects and preservation of unrelated records verified');
};
