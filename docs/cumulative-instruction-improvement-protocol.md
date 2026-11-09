# Cumulative instruction-improvement protocol

1. **Agent preparation:** Use `gpt-6.1-sol` with `high` reasoning effort in Codex to write the task agent's initial instructions and implementation, along with its tools, evaluation checks, and experiment runner. Complete this engineering work before measured task execution.

2. **Task execution:** Use `gpt-6.1-sol` with `low` reasoning effort through the OpenAI Agents API. Create a fresh session for every task run, loading the instruction version being tested. Keep all model calls, tool calls, and follow-up turns for that task within the same session. Keep the model and reasoning settings fixed across instruction versions.

3. **Instruction revision:** Use `gpt-6.1-sol` with `high` reasoning effort through the Responses API. A separate component calls the same general-purpose model using the [general instruction-revision prompt](#general-instruction-revision-prompt) and a separately supplied study evidence package. It analyzes accumulated execution evidence and generates revised task-agent instructions, then automatically applies a valid candidate for evaluation. No model fine-tuning is involved.

4. **Hosted runtime:** Use the Agents API's [managed Codex harness](https://developers.openai.com/api/docs/guides/agents-api/architecture) for the model-and-tool loop and an [OpenAI-hosted sandbox](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted) (`environment.type: openai_hosted`) for command execution, MCP servers, and task data. Give each task run a fresh sandbox and independent starting state. The local experiment controller starts and monitors runs and collects evidence. Use structured outputs and automated native approvals. Freeze code, dependency versions, tools, permissions, and business rules before evaluation.

5. **Baseline:** Start with competent shared instructions. Validate the environment and graders against known correct and incorrect outcomes. Do not weaken the baseline to manufacture errors.

6. **Allowed changes:** Change only the task agent's instructions. Keep models, reasoning settings, tools, code, business rules, and graders fixed. Impose no instruction-length restriction.

7. **Cumulative learning:** Every improvement request receives the original instructions, all subsequent instruction versions and changes, execution traces, correctness results, timing, cost, and conclusions from every previous valid agent execution and instruction-revision attempt, including unsuccessful valid attempts. Runs invalidated by tool, harness or grader defects are invalid measurements, not agent-performance observations. Keep their diagnostics and costs separately; they do not expand the scenario count and must not be used as agent-failure feedback. Never selectively remove unfavorable valid agent results.

8. **Verify the feedback:** Check the actual improvement-request payload for the required history before sending it. Record the supplied evidence and instruction versions. Files saved outside the request are not evidence that the model received them.

9. **Continue the chain:** Improve the preceding instruction version using all accumulated evidence. Earlier changes may be corrected or undone. Choosing a different version for use must not reset the experimental chain or remove prior feedback.

10. **Evaluation separation:** Keep upcoming evaluation cases hidden from the instruction-revision component. Once evaluation results inform a later improvement, treat those cases as previously seen and use fresh cases for later evaluation.

11. **Comparisons:** Compare each new version against the preceding version and the original baseline on matching evaluation cases. Use independent starting state, balanced execution order, and the repetitions defined in the separate study specification. Keep the caching policy consistent and record actual cache usage.

12. **Evaluation framework:** Use Promptfoo with fixed, validated checks of actual outputs, execution traces, and resulting business state. Keep graders outside the improvement process's control. Display instruction versions side by side with their traces and task metrics.

13. **Task timing:** Start timing when a ready environment receives the initial request. Stop at parsed task completion and final required customer handling. Include model, tool, controller, and automated approval time. Exclude setup, grading, evidence collection, cleanup, and pauses.

14. **Cost measure:** Use estimated task-model cost for instruction-version comparisons. Sum uncached input, cache-read input, cache-write input, and output charges across all model calls needed for the task, using nonoverlapping token categories and the same recorded rates. Count billed reasoning tokens within output, without charging for them twice. Report mean model cost per attempted task and cost per successful task, including spending on unsuccessful attempts. Report hosting, instruction generation, grading, and other overhead separately. Keep estimates distinct from provider-reported charges; retain ranges when usage or billing details are incomplete.

15. **Time tolerance:** Use **5%**, relative to the comparison version's median task time for the same task. A change between -5% and +5% is inside the practical tolerance. Do not impose an additional absolute-time threshold.

16. **Cost tolerance:** Use **5%**, relative to the comparison version's mean estimated model cost per task for the same task. A change between -5% and +5% is inside the practical tolerance. Do not impose an additional absolute-dollar threshold. If the comparison cost is zero, report the absolute difference and mark the percentage undefined.

17. **Variability:** Report observed percentage changes and paired 95% confidence intervals. Assess differences separately for each task and use equal task weighting for an overall summary. Label conclusions inconclusive when execution variability or billing uncertainty prevents a decision under the 5% margins. Report small observed gains even when they do not establish a meaningful difference.

18. **Performance decisions:** With correctness preserved, an improvement greater than 5% in time or cost can qualify as a meaningful benefit when the other measure increases by no more than 5% and the uncertainty supports that conclusion. Report larger cost/time tradeoffs explicitly. A version-selection decision must not terminate the planned learning chain or withhold feedback from later attempts.

19. **Correctness:** Grade business outcomes and authorization independently from efficiency. Faster or cheaper execution cannot excuse new correctness or authorization failures. Keep those failures available as feedback for subsequent improvement.

20. **Evidence and reporting:** Record correctness, time, model cost, token categories, model activity, tool calls, approval steps, and controller activity with clearly defined units. Save checkpoints, support pauses, and resume without silently repeating completed work or replacing unfavorable results. Classify infrastructure failures separately from agent decisions. Verify actual execution against this protocol before reporting conclusions and disclose deviations and unresolved questions.

21. **Separate study specification:** Define scenarios, task-specific success checks, development/evaluation case assignments, task counts, improvement-round counts, repetition counts, and the resulting execution schedule separately. Calculate the total cost estimate and execution authorization from that schedule; these are not instruction-version performance tolerances.

## General instruction-revision prompt

Keep this reusable instruction-revision prompt fixed within an agreed study. Record its exact text and hash with each request. Supply study-specific task requirements, evidence, schedules, and authorized exceptions in the input package.

```text
You are the instruction-improvement component in a controlled engineering study.
Produce the next instruction version for the task-execution agent by revising
the immediately preceding version using all supplied execution evidence.

Objective
Preserve or improve task correctness, authorization and truthful reporting.
Seek evidence-supported instruction changes that could reduce task-model cost
or task completion time while preserving required outcomes. Use the supplied
metric definitions, uncertainty and decision rules. A competent passing baseline
is a valid result; do not manufacture errors or assume that improvement must exist.

Allowed intervention
Change only the task agent's instructions. Preserve the model and reasoning
settings, tools, implementation, business rules, permissions, output contract,
graders, task requirements and measurement methods. Do not instruct the agent to
alter those controls, manipulate results or consult withheld evaluation material.
Retain required approvals, evidence checks and customer handling. There is no
instruction-length restriction or brevity target. Prefer guidance that transfers
across the study's tasks rather than memorizing individual case answers.

Evidence review
Examine the original instructions, preceding instructions, every later version
and change, and every previous valid agent execution and instruction-revision
attempt, including unsuccessful valid attempts. Never exclude unfavorable valid
agent results. Invalid measurements caused by implementation defects are setup
diagnostics, not agent failures or additional study scenarios. Review
execution traces, actual business/task outcomes, authorization results, customer
outputs, task timing, token/cache usage, model cost, tool/controller activity and
prior conclusions. Respect the stated counting units and measurement boundaries.
Files or links mentioned in the package are not evidence you have read unless
their required content is actually supplied. Identify missing or contradictory
evidence; do not invent observations, requirements or causal explanations.

Distinguish agent decisions from infrastructure, approval-transport, service,
grading and evidence-collection faults. Use the valid learning evidence supplied.
Do not treat a corrected implementation bug
as an agent reasoning failure or introduce instruction workarounds for it. Report
necessary changes outside instructions separately; they are not this intervention.

Revision method
Identify concrete instruction-related opportunities supported by the evidence.
Consider correctness, unnecessary or repeated work, use of available tools,
context/token costs and completion time without removing necessary safeguards.
Fewer tool calls or shorter instructions alone do not establish lower cost or
latency. Separate observed facts from explanations and predicted benefits.

Revise the immediately preceding instruction version. Earlier changes may be
corrected or undone, but retain the complete learning history. An earlier
deployment/version-selection decision does not reset this chain. When the study
uses shared instructions, return one shared instruction set across its tasks.

Produce one complete candidate. Explain substantive changes using attempt and
trace references, their expected effects on correctness, cost and time, and their
regression risks. If no change is justified, return the preceding instructions
unchanged and explain why. Do not force a cosmetic revision. If required evidence
is missing, identify the omission instead of presenting an unsupported candidate.

Output
Return the required structured response with the complete replacement instructions,
evidence-linked changes, expected effects, limitations and out-of-scope issues.
Predicted benefits are hypotheses for the subsequent evaluation. Do not declare
the candidate successful, select the deployment version, change acceptance rules,
add candidates or extend the execution schedule. Those decisions belong to the
fixed evaluation and experiment controller.
```

## Required revision-request evidence package

Supply and verify the following content in the actual request, using a consistent structured representation:

- **Fixed study context:** Required task outcomes and operating conditions, the instruction-only intervention, fixed model/runtime/tool/permission/output contracts, metric definitions and decision rules, and any explicitly authorized study exceptions. Include the task requirements and rules needed to interpret previous execution evidence. Keep upcoming evaluation cases hidden.
- **Instruction history:** The original instructions, immediately preceding instructions, every subsequent instruction version and change, version identifiers and hashes. Identify which version produced each attempt. Include selection decisions without confusing the selected deployment version with the learning-chain predecessor.
- **Execution history:** All preceding valid agent executions and instruction-revision attempts and their supplied requests, relevant initial/final state, outputs, action/tool traces, approval events, correctness/authorization/reporting results, task times, token/cache usage, estimated task-model costs and other measured activity. Preserve counting units, cost uncertainty and timing boundaries. Include unsuccessful and incomplete valid agent/instruction attempts with their status and available evidence. Invalid implementation-fault measurements are setup diagnostics and remain outside agent-performance feedback.
- **Conclusions and fault accounting:** Interpretations and limitations of valid measurements. Preserve pre-existing infrastructure diagnostics and accounting separately, without presenting implementation faults as agent failures or extra scenarios. Provide small observed gains as observations even when they do not establish a meaningful improvement.

Do not substitute an external file path, a hash, a summary that omits required history, or an assurance that records exist for supplying that history. Lossless deduplication within the request is permitted when all referenced content is present and reconstructable. Validate coverage and token fit before sending. A missing history or capacity problem must not silently truncate evidence or reset the chain.

## Required revision response and application

The structured response must contain these logical fields; use a fixed validated schema in the implementation:

| Field | Required content |
| --- | --- |
| `status` | `revised`, `unchanged`, or `insufficient_evidence` |
| `instructions` | Complete replacement instructions; identical to the preceding version for `unchanged`, and null for `insufficient_evidence` |
| `rationale` | Evidence-based explanation of the proposed revision, unchanged decision, or evidence insufficiency |
| `changes` | Each substantive change, supporting attempt/trace references, expected correctness/cost/time effects, and regression risks |
| `evidence_limitations` | Missing evidence, uncertainty and limits on interpretation |
| `outside_instruction_scope` | Necessary tool/code/policy/harness/grader changes that cannot be implemented through this revision |

Before a revision request, freeze and record the general prompt, study package and schema. Verify that the complete required history is actually present, and retain the exact request and model settings. Afterward, validate the response and record the candidate, rationale, usage and cost. Automatically apply a valid `revised` or `unchanged` instruction set for the planned evaluation; do not apply an `insufficient_evidence` response or silently repair/regenerate an invalid response. Retain unsuccessful attempts and follow the agreed schedule and recovery rules. Candidate generation is not performance validation, and an unchanged candidate does not itself terminate a planned learning chain.
