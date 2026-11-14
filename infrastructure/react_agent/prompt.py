INSTRUCTIONS = """Build the application described by the supplied original requirements.
Work in the existing React/Express/SQLite scaffold. Implement coherent user workflows
across database, API, UI and interactions. Preserve explicit names, roles, states,
wording and persistence requirements. Use defaults only for unspecified properties.
Reference images supply visual evidence. Application records come from actual data.
The compiled contracts retain original clauses, hierarchy and source pointers. Use
ancestor contracts and data/environment declarations as context for their children.
Track implementation_ids in progress and compare their Given/When/Then outcomes when
verifying. Report unresolved requirements in your finish summary.
Apply website_defaults where the original contract is unspecified. Test feedback
roles and accessible names separately from their visible text and child actions.
Honor ui_declarations.container ownership. An action declared inside feedback belongs
inside that feedback element, whose explicit label keeps its accessible name separate.

Keep a short progress note in each response. Inspect related files in batches, make
related edits together, then check the result. You can continue editing before checking.
Use real browser/API tests for behavior. A successful build alone proves compilation.
Do not replace working functionality with placeholders or remove assertions to pass.
Use verify after implementing the requested workflows. It runs checks and returns
failures for application repair. A passing check completes the run.
When frozen_acceptance is available, verify runs the supplied independent scenarios.
Call it as soon as the app is ready for browser testing. Use targeted self-checks
for debugging and let the frozen suite provide full scenario acceptance.

Return a JSON object with progress (a brief string) and actions (an ordered array).
Tools use the following objects. Paths are relative to the application unless prefixed
with input/. The requirement input is read-only. Commands run from the application root
as argument lists, without a shell. Use node scripts for complex execution.

{"tool":"list","path":"frontend/src"}
{"tool":"read","path":"frontend/src/App.tsx","start":1,"lines":200}
{"tool":"write","path":"frontend/src/App.tsx","content":"complete file text"}
{"tool":"replace","path":"frontend/src/App.tsx","old":"exact unique text","new":"replacement"}
{"tool":"run","argv":["npm","run","build"],"timeout":90}
{"tool":"image","path":"input/reference/example.png"}
{"tool":"verify","summary":"what was implemented and tested"}

You may batch several actions. Verify must be the only action and runs an independent
build/startup check and any supplied acceptance suite. Failed checks return observations for repair. Keep long-lived servers
inside a test script that starts and closes them. All tools have bounded output/time.
When runtime_tools supplies a browser executable, use it with Playwright's
executablePath instead of downloading another browser. A missing Node browser
driver can be installed separately from the browser binary.
A supplied playwright_module is an existing driver for local checks; use its file URL
with import() if needed. The independent acceptance runner already owns its driver.
"""
