"""Validate the website test language and its deterministic Playwright backend."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import yaml

from infrastructure.react_agent.requirements import compile_requirements, resolve_source
from infrastructure.react_agent.test_plan import compile_plan, resolve_names, validate_plan
from infrastructure.react_agent.verification import BrowserSuite


class BrowserPlans(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input"
        self.input.mkdir()
        (self.input / "requirements.yaml").write_text('''id: R
description: 'Click Save to show "Saved"(role=status) with "Undo"(role=button). Undo shows Undone.'
''', encoding="utf-8")
        self.raw, self.contracts = compile_requirements(self.input)

    def plan(self):
        return {"cases": [{"requirement_id": "R", "title": "Save and undo", "source": "requirements.yaml#/description",
            "steps": [
                {"op": "goto", "url": "/"},
                {"op": "click", "target": {"role": "button", "name": "Save"}},
                {"op": "expect", "target": {"declaration": "UI-1"}, "check": "visible"},
                {"op": "expect", "target": {"declaration": "UI-2"}, "check": "visible"},
                {"op": "click", "target": {"declaration": "UI-2"}},
                {"op": "expect", "target": {"text": "Undone"}, "check": "visible"},
            ]}]}

    def test_code_and_manifest_share_the_same_case_objects(self):
        plan = self.plan()
        report = compile_plan(self.input, self.root / "tests", plan)
        self.assertEqual(report["cases"][0]["title"], "R / Save and undo")
        self.assertEqual(report["cases"][0]["ui_checks"], ["UI-1", "UI-2"])
        self.assertEqual(report["unchecked_ui_declarations"], [])
        self.assertNotIn("ui_checks", plan["cases"][0])
        source = (self.root / "tests/acceptance.spec.ts").read_text(encoding="utf-8")
        self.assertIn('"title": "Save and undo"', source)
        self.assertIn('test(plan.requirement_id + " / " + plan.title', source)

    def test_case_requires_real_assertions_and_requirement_coverage(self):
        for variant in ("no assertion", "missing requirement", "duplicate"):
            plan = self.plan()
            if variant == "no assertion":
                plan["cases"][0]["steps"] = [{"op": "goto", "url": "/"}]
            elif variant == "missing requirement":
                self.contracts["implementation_ids"].append("OTHER")
            else:
                plan["cases"].append(deepcopy(plan["cases"][0]))
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                validate_plan(self.raw, self.contracts, plan)

    def test_browser_operations_are_explicit_and_navigation_is_local(self):
        for step in [{"op": "run", "code": "anything"}, {"op": "goto", "url": "https://example.com"},
                     {"op": "goto", "url": "//example.com"}, {"op": "goto", "url": "/\\example.com"}]:
            plan = self.plan()
            plan["cases"][0]["steps"].insert(0, step)
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_plan(self.raw, self.contracts, plan)

    def test_declared_names_and_ownership_cannot_be_overridden_in_the_plan(self):
        for change in ({"name": "Something else"}, {"within": {"role": "main"}}):
            plan = self.plan()
            step = 2 if "name" in change else 3
            plan["cases"][0]["steps"][step]["target"].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "compiled contract"):
                validate_plan(self.raw, self.contracts, plan)

    def test_an_unspecified_container_can_be_scoped_to_original_workflow_context(self):
        plan = self.plan()
        plan["cases"][0]["steps"][2]["target"]["within"] = {"role": "main"}
        validate_plan(self.raw, self.contracts, plan)

    def test_missing_variables_invalid_assertions_and_bad_sources_are_rejected(self):
        for variant in ("variable", "assertion", "source", "count"):
            plan = self.plan()
            if variant == "variable":
                plan["cases"][0]["steps"][1]["target"]["name"] = "${missing}"
            elif variant == "assertion":
                plan["cases"][0]["steps"][2]["check"] = "always_true"
            elif variant == "count":
                plan["cases"][0]["steps"][2].update(check="count", value=True)
            else:
                plan["cases"][0]["source"] = "requirements.yaml#/missing"
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                validate_plan(self.raw, self.contracts, plan)

    def test_failed_validation_leaves_original_plan_and_output_intact(self):
        plan = self.plan()
        plan["cases"][0]["steps"].append({"op": "unknown"})
        original = deepcopy(plan)
        with self.assertRaises(ValueError):
            compile_plan(self.input, self.root / "tests", plan)
        self.assertEqual(plan, original)
        self.assertFalse((self.root / "tests").exists())

    def test_source_pointers_resolve_escaped_dictionary_keys_and_list_indexes(self):
        source = {"a/b": {"~key": [{"Then": "observable"}]}}
        self.assertEqual(resolve_source(source, "requirements.yaml#/a~1b/~0key/0/Then"), "observable")
        for pointer in ("requirements.yaml#/a~1b/~0key/1", "requirements.yaml#/missing", "application.ts#"):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                resolve_source(source, pointer)

    def test_explicit_original_name_resolves_before_feedback_default(self):
        (self.input / "requirements.yaml").write_text('''id: R
description: 'Click Save to show "Saved"(role=status). Its accessible name is "Confirmation".'
''', encoding="utf-8")
        raw, contracts = compile_requirements(self.input)
        resolution = {"UI-1": {"name": "Confirmation", "source": "requirements.yaml#/description",
                                "evidence": 'Its accessible name is "Confirmation".'}}
        declarations = resolve_names(raw, contracts, resolution)
        self.assertEqual(declarations["UI-1"]["resolved_accessible_name"], "Confirmation")
        self.assertEqual(declarations["UI-1"]["label"], "Saved")
        self.assertEqual(contracts["ui_declarations"][0]["default_accessible_name"], "Saved")

    def test_explicit_unnamed_feedback_can_override_the_default(self):
        (self.input / "requirements.yaml").write_text('''id: R
description: 'Show "Saved"(role=status). This status has no accessible name.'
''', encoding="utf-8")
        raw, contracts = compile_requirements(self.input)
        declarations = resolve_names(raw, contracts, {"UI-1": {"name": "", "source": "requirements.yaml#/description",
                                       "evidence": "This status has no accessible name."}})
        self.assertEqual(declarations["UI-1"]["resolved_accessible_name"], "")

    def test_name_overrides_require_actual_naming_evidence(self):
        for resolution in (
            {"name": "Different", "source": "requirements.yaml#/description", "evidence": "Click Save"},
            {"name": "", "source": "requirements.yaml#/description", "evidence": "Click Save"},
            {"name": "Different", "source": "requirements.yaml#/description", "evidence": "absent clause"},
        ):
            with self.subTest(resolution=resolution), self.assertRaises(ValueError):
                resolve_names(self.raw, self.contracts, {"UI-1": resolution})

    @unittest.skipUnless(os.environ.get("REACT_BROWSER_TESTS") == "1", "Enable REACT_BROWSER_TESTS for live browser checks")
    def test_browser_backend_accepts_valid_markup_and_rejects_semantic_mutants(self):
        directory = self.root / "suite"
        compile_plan(self.input, directory, self.plan())
        suite = BrowserSuite(directory, Path(os.environ["REACT_PLAYWRIGHT_CLI"]),
                             channel=os.environ.get("REACT_BROWSER_CHANNEL"))
        collected = suite.collect(self.root / "collection")
        self.assertTrue(collected["passed"], collected)
        current = {"html": ""}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = current["html"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        controls = '<span>Saved</span><button id="undo">Undo</button>'
        bodies = {
            "valid": '<div role="status" aria-label="Saved">' + controls + '</div>',
            "unnamed": '<div role="status">' + controls + '</div>',
            "wrong_name": '<div role="status" aria-label="Saved Undo">' + controls + '</div>',
            "wrong_text": '<div role="status" aria-label="Saved"><span>Different message</span><button id="undo">Undo</button></div>',
            "orphan_action": '<div role="status" aria-label="Saved"><span>Saved</span></div><button id="undo">Undo</button>',
        }

        def html(body):
            return '<html><body><button id="save">Save</button><div id="feedback" hidden>' + body + '''</div>
<p id="undone" hidden>Undone</p><script>
document.querySelector('#save').onclick=()=>{document.querySelector('#feedback').hidden=false;};
document.querySelector('#undo').onclick=()=>{document.querySelector('#feedback').hidden=true;document.querySelector('#undone').hidden=false;};
</script></body></html>'''

        try:
            for name, body in bodies.items():
                current["html"] = html(body)
                result = suite(url, self.root / name, 45)
                with self.subTest(variant=name):
                    self.assertEqual(result["passed"], name == "valid", result)
                    self.assertEqual(result["kind"], "ACCEPTANCE_PASSED" if name == "valid" else "ASSERTION_FAILURE")
            for name, clause, accessible_name, body in [
                ("explicit_name", 'Its accessible name is "Confirmation".', "Confirmation",
                 '<div role="status" aria-label="Confirmation">' + controls + '</div>'),
                ("explicit_unnamed", "This status has no accessible name.", "", bodies["unnamed"]),
            ]:
                (self.input / "requirements.yaml").write_text(yaml.safe_dump({**self.raw, "extra": clause}), encoding="utf-8")
                plan = self.plan()
                plan["name_resolutions"] = {"UI-1": {"name": accessible_name,
                    "source": "requirements.yaml#/extra", "evidence": clause}}
                directory = self.root / (name + "-suite")
                compile_plan(self.input, directory, plan)
                resolved_suite = BrowserSuite(directory, Path(os.environ["REACT_PLAYWRIGHT_CLI"]),
                                              channel=os.environ.get("REACT_BROWSER_CHANNEL"))
                current["html"] = html(body)
                result = resolved_suite(url, self.root / name, 45)
                with self.subTest(variant=name):
                    self.assertTrue(result["passed"], result)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @unittest.skipUnless(os.environ.get("REACT_BROWSER_TESTS") == "1", "Enable REACT_BROWSER_TESTS for live browser checks")
    def test_application_fixture_gives_each_case_a_fresh_data_file(self):
        (self.input / "requirements.yaml").write_text('''id: ROOT
children:
- id: FIRST
  description: The first scenario starts from a fresh application.
- id: SECOND
  description: The second scenario also starts from a fresh application.
''', encoding="utf-8")
        plan = {"cases": [{"requirement_id": rid, "title": "Fresh state", "source": f"requirements.yaml#/children/{index}",
                           "steps": [{"op": "goto", "url": "/"},
                                     {"op": "expect", "target": {"role": "heading", "name": "Visits 1"}, "check": "visible"}]}
                          for index, rid in enumerate(("FIRST", "SECOND"))]}
        directory = self.root / "isolated-suite"
        compile_plan(self.input, directory, plan)
        application = self.root / "application"
        server = application / "backend/dist/server.js"
        server.parent.mkdir(parents=True)
        server.write_text('''const http=require('node:http');
const fs=require('node:fs');
const filename=process.env.DATABASE_URL;
let count=fs.existsSync(filename)?Number(fs.readFileSync(filename,'utf8')):0;
const server=http.createServer((request,response)=>{
  if(request.url!=='/'){response.writeHead(404);response.end();return;}
  count+=1;fs.writeFileSync(filename,String(count));
  response.setHeader('Content-Type','text/html');
  response.end('<html><body><h1>Visits '+count+'</h1></body></html>');
});
server.listen(Number(process.env.PORT),'127.0.0.1',()=>{
  console.log('Application listening at http://127.0.0.1:'+server.address().port);
});
''', encoding="utf-8")
        suite = BrowserSuite(directory, Path(os.environ["REACT_PLAYWRIGHT_CLI"]),
                             channel=os.environ.get("REACT_BROWSER_CHANNEL"))
        result = suite.for_application(application)("http://127.0.0.1:9", self.root / "isolated-results", 60)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["stats"]["expected"], 2)


if __name__ == "__main__":
    unittest.main()
