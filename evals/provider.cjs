const fs = require('node:fs');
const path = require('node:path');
module.exports = class EvidenceProvider {
  constructor(options) { this.root = options.config.root; }
  id() { return 'retail-workflow-completed-evidence'; }
  async callApi(prompt, context) {
    const record = JSON.parse(fs.readFileSync(path.join(this.root, context.vars.evidence_file), 'utf8'));
    return {output: JSON.stringify(record.final), cost: 0,
      tokenUsage: {total: 0, prompt: 0, completion: 0},
      metadata: {record_id: record.id, evidence: record}};
  }
};
