import asyncio
import base64
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import app as application


PROJECT_ROOT = application.runtime.resource_root
NODE = shutil.which("node")
NODE_HARNESS = r"""
const vm = require('vm');
const source = Buffer.from(process.argv[1], 'base64').toString('utf8');
const responses = JSON.parse(process.argv[2]);
const steps = Number(process.argv[3]);
const timers = [];
const navigations = [];
let calls = 0;
const window = {
  fetch: async () => {
    const value = responses[calls++];
    if (value === 'error') throw new Error('temporary backend outage');
    return { ok: true, json: async () => ({ setup_complete: value }) };
  },
  location: { replace: (url) => navigations.push(url) },
  setTimeout: (callback, delay) => timers.push({ callback, delay }),
};
vm.runInNewContext(source, { window });
(async () => {
  for (let index = 0; index < steps && timers.length; index += 1) {
    const timer = timers.shift();
    await timer.callback();
  }
  process.stdout.write(JSON.stringify({ calls, navigations, timers: timers.map((timer) => timer.delay) }));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def setup_script() -> str:
    template = (PROJECT_ROOT / "templates/display_setup_required.html").read_text(
        encoding="utf-8"
    )
    scripts = re.findall(r"<script>(.*?)</script>", template, flags=re.DOTALL)
    if len(scripts) != 1:
        raise AssertionError("Expected one inline setup-status script")
    return scripts[0]


def run_setup_script(responses: list[bool | str], steps: int) -> dict:
    source = base64.b64encode(setup_script().encode()).decode()
    result = subprocess.run(
        [NODE, "-e", NODE_HARNESS, source, json.dumps(responses), str(steps)],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


class DisplaySetupTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_status_endpoint_reports_current_state(self):
        for expected in (False, True):
            with self.subTest(setup_complete=expected), patch.object(
                application.db, "setup_complete", return_value=expected
            ):
                self.assertEqual(
                    await application.setup_status(), {"setup_complete": expected}
                )

    @unittest.skipUnless(NODE, "Node.js is required for the browser-script behavior test")
    async def test_setup_false_does_not_navigate_or_reload(self):
        result = await asyncio.to_thread(run_setup_script, [False], 1)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["navigations"], [])
        self.assertEqual(result["timers"], [3000])

    @unittest.skipUnless(NODE, "Node.js is required for the browser-script behavior test")
    async def test_setup_becoming_true_navigates_once(self):
        result = await asyncio.to_thread(run_setup_script, [False, True], 3)
        self.assertEqual(result["calls"], 2)
        self.assertEqual(result["navigations"], ["/display"])
        self.assertEqual(result["timers"], [])

    @unittest.skipUnless(NODE, "Node.js is required for the browser-script behavior test")
    async def test_transient_endpoint_failure_retries_without_navigation(self):
        result = await asyncio.to_thread(run_setup_script, ["error"], 1)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["navigations"], [])
        self.assertEqual(result["timers"], [3000])

    async def test_normal_display_does_not_include_setup_polling(self):
        normal_display = (PROJECT_ROOT / "templates/display.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("/api/setup/status", normal_display)
        self.assertNotIn("checkSetupStatus", normal_display)


if __name__ == "__main__":
    unittest.main()
