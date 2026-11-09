# Recursive Agent Instruction Improvement

Run a controlled study that changes a retail agent's instructions while keeping its model, tools, rules, and grader fixed. The runner measures a baseline, generates a revision from your run evidence, and compares both instruction versions on held-out synthetic cases. Each additional round gives the reviser the earlier instructions, executions, and revision attempts before evaluating on fresh cases.

The published write-up covers two simulated retail studies. One compared Baseline, Revision 1, and Revision 2 across twelve distinct workflows. The other compared two independently drafted revisions with Baseline on held-out return-and-exchange cases. Both studies measured correctness, task time, and estimated model cost. [Recursive Self-Improvement Meets a Strong Baseline](https://blog.latentthoughts.com/recursive-self-improvement-meets-a-strong-baseline)

For the experimental method behind the kit, see [Engineering Experiments: From Hypothesis to Understanding](https://blog.latentthoughts.com/from-hypothesis-to-understanding-a-practical-framework-for-applied-ai-engineering-experiments).

## Setup

Use Python 3.14 and Node.js 22.22 or newer on macOS or Linux. Clone the repository and install the pinned controller and Promptfoo dependencies.

```sh
git clone https://github.com/garystafford/recursive-agent-instruction-improvement.git
cd recursive-agent-instruction-improvement
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm ci --prefix evals
```

Run the offline check before using an API key. It starts the simulated MCP service, exercises the reference actions, and verifies that Promptfoo accepts correct outcomes and rejects faults in state, reporting, and authorization. Give it a fresh output directory.

```sh
.venv/bin/python -m refund_pilot.workflows.study check --out runs/preflight
```

## Run a study

Copy the example config and set the four token rates in USD per million tokens, the local spending budget, and the task and hosting allowances for your run. Choose rates that cover the request sizes you plan to use. Refer to your provider's pricing for any long-context or caching rates. Set `OPENAI_API_KEY` in your shell using a project with access to the configured model through the managed Agents API and Responses API. [OpenAI pricing](https://developers.openai.com/api/docs/pricing)

```sh
cp examples/study.json study.local.json
# Edit study.local.json and set OPENAI_API_KEY before proceeding.
.venv/bin/python -m refund_pilot.workflows.study run \
  --config study.local.json --out runs/example --allow-paid
```

The example schedules one development case, one revision request, and two held-out cases evaluated once per version. Each entry in `evaluation_rounds` schedules a new revision and supplies a fresh set of evaluation cases. Use disjoint case IDs for development and for each evaluation round. The runner compares the revision, baseline, and preceding revision on identical starting state within a round and rotates version order. Each task gets a fresh hosted session and SQLite store. The revision step receives the completed evidence and earlier revision attempts, including valid task failures.

The runner checks a local estimated spending allowance. Hosted infrastructure charges and model usage can differ from the local estimates. Review actual charges in your provider account. Rerun the same command with the same output directory and config to continue after a clean interruption between operations. Incomplete or ambiguous paid operations pause the study for inspection so the runner avoids duplicate submissions.

Open `runs/example/summary.json` for the comparison and `runs/example/comparison.csv` for per-attempt results. The summary separates task-model estimates, revision estimates, and hosting allowances. A single repetition is a feasibility check. Use more repetitions and additional cases per workflow for stronger comparisons. Promptfoo verifies structured outcomes, business state, and approvals. Review the free-text customer message separately.

## Study assets

- [Cumulative instruction-improvement protocol](docs/cumulative-instruction-improvement-protocol.md) includes the reusable revision prompt and evidence requirements.
- [Retail workflow suite](docs/retail-workflow-study-specification.md) defines T01–T12. The packaged runner includes [one runnable fixture per workflow](refund_pilot/workflows/cases.py) and [shared baseline instructions](prompts/workflow-baseline.txt). Add cases and independent checks for broader coverage within a workflow.
- [Return-and-exchange variation catalog](docs/retail-return-exchange-variations.md) defines V01–V12 and maps to the [separate fixture generator](refund_pilot/retail/fixtures.py). It produces development and held-out conversation fixtures for a return-and-exchange harness. The quickstart runner executes the T suite.
- [MCP service](refund_pilot/workflows/service.py) provides simulated business operations and exact-argument approvals. [Promptfoo assertions](evals/assertions.cjs) grade evidence outside the agent environment.

## License

[MIT](LICENSE).
