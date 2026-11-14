# Lightweight application-builder experiment

Research checked on 2026-11-14. The experiment lives on `experiment/react-lite`.
Run it from the existing repository with its current Python dependencies.

## Observed baseline

The supplied 2026-11-07 Keep log records 60m41s of agent execution and 152
`MODEL CALL` entries. The intervals between call/output markers sum to about
49m44s. This includes provider generation and network waiting.

Stage 06 takes 6m40s and fails after repeated obligation-propagation feedback.
Stage 11 takes 4m03s and fails on the missing upstream contract. Stage 12 then
takes 27m45s, including a second acceptance-generation/review workflow starting
at 16:16:47. Five attempts to read disallowed source files appear in that final
workflow. These observations describe the archived run. Current-branch timing
and costs require a new measurement under matching conditions.

## Framework and strategy comparison

| Approach | Relevant mechanism | Experiment decision |
| --- | --- | --- |
| mini-SWE-agent v2 | Linear conversation, query/action/observation loop, explicit limits and saved trajectory | Use this execution structure and compare complete runs |
| Deep Agents | Filesystem tools, context offloading, configurable middleware and model-specific profiles | Keep as an integration candidate when context management is measured as a bottleneck |
| Deep Agents v0.7 | Shorter base prompting, smaller tool descriptions, opt-in todo middleware | Start with a compact tool contract and a progress string |
| smolagents | Multi-step loop controlled by model outputs, tools or executable code | Use a similarly direct loop with the existing JSON-compatible transport |
| Anthropic long-running app harness | Feature-by-feature implementation, browser evaluation, session handoffs | Borrow feature-level verification; measure orchestration cost before adding roles |

These projects address different benchmarks and models. Their published scores
do not predict ArcBench performance. The current prototype is a small local
implementation of the loop pattern with the repository's transport and scaffold.

Sources, checked directly from the projects' documentation and engineering posts

- [mini-SWE-agent execution loop](https://mini-swe-agent.com/latest/advanced/control_flow/)
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents v0.7, 2026-07-29](https://www.langchain.com/blog/deep-agents-v0-7)
- [Model-specific harness profiles, 2026-04-29](https://www.langchain.com/blog/tuning-deep-agents-different-models)
- [Trace-driven harness improvements, 2026-02-17](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- [smolagents multi-step execution](https://huggingface.co/docs/smolagents/conceptual_guides/intro_agents)
- [Application-development harness, 2026-03-24](https://www.anthropic.com/research/harness-design-long-running-apps)

## Execution differences

| Concern | Existing compiler | Experimental runner |
| --- | --- | --- |
| Scheduling | Thirteen ordered passes with per-task loops | One ongoing implementation conversation |
| Intermediate contracts | Schema, obligations, API P/Q, UI IR, trigger plans | Source-linked requirement clauses and compact UI declarations |
| Editing | Stage-owned writable scopes and gates | Cross-layer batches of related edits |
| Context | Stage payload, selected files, discovery and feedback | Append action and observation messages |
| Checking | Many stage-specific generation/review/repair gates | A verification action that builds, starts and runs a frozen external suite |
| Failure | Record failed passes and attempt later passes | Return tool failures to the same conversation; propagate transport failures |
| Measurement | Existing stage/model logs | JSONL trajectory and aggregate time/token report |

## Running the prototype

Compile a separate acceptance suite with one model request and check the actual
case inventory using an installed Playwright CLI.

```powershell
python -m infrastructure.react_agent.acceptance INPUT -o TESTS --playwright-cli PLAYWRIGHT_CLI
```

Then run implementation against the frozen suite.

```powershell
python -m infrastructure.react_agent.runner INPUT -o OUTPUT --max-steps 40 --time-budget 900 --acceptance-dir TESTS --playwright-cli PLAYWRIGHT_CLI
```

`INPUT` contains the original `requirements.yaml` and reference materials.
`OUTPUT` is a separate application directory. The runner uses the existing
environment configuration and model credentials. The budget is in seconds.
`--skip-install` supports an application with dependencies already prepared.

The model can list/read files, write whole files, perform unique replacements,
execute argument-list commands and request reference-image analysis. Tools run
from the application directory. Commands execute with the runner's OS permissions,
so an isolated execution environment is needed for untrusted tasks. File-tool
path checks provide application/input boundaries; arbitrary commands have normal
process-level access. Original requirement files are read-only through file tools.

`--browser-channel chrome` selects installed Chrome for local browser checks.
Interrupted runs can continue from their saved conversation with `--resume`.
For an already installed workspace, `--skip-install` avoids repeating installation.
The requirement-source hash is checked before a resumed run publishes artifacts.
The verification action builds the application, starts its real server on a
temporary port with a fresh database, checks health and the root HTML response,
and executes the supplied suite. It stops the owned process tree afterward.
Without a supplied suite the success status is `BUILD_AND_STARTUP_PASSED`, with
`behavior_verified: false`. A passing external suite produces `ACCEPTANCE_PASSED`.
Requirement-level results retain unexecuted cases as `UNVERIFIED`. These metrics
describe the supplied tests' coverage; additional acceptance can still find bugs.

The test runner stops after the first failure by default. The agent can repair
the cause and run the full suite again. A successful run requires all cases to
execute and pass. Expected failures, skipped cases and missing executable cases
cannot produce a passing acceptance result.

Artifacts live in `OUTPUT/.arc/`

- `react-trajectory.jsonl` contains action batches and observations.
- `react-report.json` contains status, elapsed/model/tool time and provider token usage.
- `requirements.json` preserves the original structured input.
- `requirement-contracts.json` indexes clauses, source pointers and UI declarations.
- `react-session.json` checkpoints the conversation for explicit resume.
- `verification/` retains raw Playwright reports, server output and failure artifacts.

The input compiler reuses `RequirementTree` and input-material discovery. It
retains parent constraints, scenario clauses, data/environment declarations and
unknown metadata. Its lexical UI index recognizes quoted `role=...` annotations,
templates and directly stated containment. Other natural-language relationships
remain in the original clauses for interpretation. Website defaults govern
underspecified feedback and landmark naming, with explicit requirements taking
precedence. They are project interpretation rules.

Primary-conversation token counts cover successful parsed responses, including
reported cache/reasoning token counts. Reference image analysis has a separate
call counter. Provider compatibility fallbacks, malformed response usage and
image-token totals still need fuller accounting before cost comparisons.

## Initial evidence

These local runs use the same original six-requirement Keep input extracted from
the archived result. The archived baseline ran on the platform. Hardware, network
and cache differences prevent treating the timing ratio as a controlled speedup.

| Run | Elapsed | Primary turns | Image analyses | External result |
| --- | --- | --- | --- | --- |
| Keep v1 | 10m31s | 20 | 4 | 8/11 |
| Keep v2 | 7m34s | 16 | 2 | 9/11 |
| Keep v3 with external repair gate | 10m18s | 17 | 3 | 11/11 |
| Keep v4 with reusable driver and verify action | 4m40s | 10 | 2 | Generated suite 11/11, original external suite 11/11 |
| BookStack Lite v1 | 13m13s | 31 | 3 | 12/12 |

V1 omitted a named status contract. V2 supplied that name on a child element,
leaving Undo outside the status container. V3 used the source-linked containment
information and corrected a misplaced navigation landmark name after the first
external failure. It then passed the same eleven-case suite within the existing
conversation.

Test compilation also needs direct validation. The first generated suite passed
the known-defective V1 application. The next suite incorrectly required literal
visible text for a named navigation landmark. The third suite passed all eleven
cases on a separately verified local control and rejected the three known status
cases on V1. Its single compilation call took about 97 seconds.

A reasoning-disabled test compilation took about 22 seconds, compared with the
roughly 97-second low-reasoning run. Its manifest claimed an executable workspace
test that was absent from the source files. The Playwright collection check
detected this mismatch. This experiment supports validating generated evidence
against actual collected cases before using token/time reductions as improvements.

Artifacts for these experiments are stored under `output/react-experiment/`.
The local control contains an explicit two-line feedback-container correction
and is a test-calibration artifact. It is separate from autonomous generation results.

BookStack's first run spent many turns discovering/installing browser tooling.
The next runner exposes the supplied verification driver's module to local checks
and presents verification as a normal check/repair action. A second BookStack
run was interrupted at turn 7 by provider HTTP 402 reporting exhausted access-key
balance. Further API experiments paused at that point. Local analysis and tests
continue independently of the model endpoint.

## Evaluation sequence

1. Exercise the loop, path boundaries, partial failures, timeout cleanup and
   truthful completion status with offline tests.
2. Verify the real scaffold can build and start locally.
3. Run the original six-requirement Keep input in a bounded model experiment.
4. Evaluate its generated app using the separately stored Keep browser tests.
5. Repeat on another task and compare latency/correctness under the same model,
   task version, dependencies and budget.

Context compaction, run-level events and seven-region traceability need integration.
The original CLI can be integrated
after the experimental execution path has broader behavior-level evidence.
