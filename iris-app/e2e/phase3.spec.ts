import { test } from '@playwright/test'

/**
 * Phase 3 boundary smoke test (REVAMP Task 3.6).
 *
 * Skipped: a real run needs a local daemon (:4002) + Express (:4001) + Vite
 * (:4173) stack and a Claude Max subscription for the chat turn. The task's
 * validation gate does not run Playwright; this file exists as a documented
 * manual-test script + a placeholder for the Phase-18 Playwright harness.
 *
 * Manual reproduction steps (run after `npm run dev`):
 *
 *   1. Create project "phase3-clearing" via POST /api/projects.
 *   2. Activate it via POST /api/projects/active.
 *   3. Start a chat turn that triggers a Bash tool call returning >2KB
 *      (e.g. "list every file under src with ls -R").
 *   4. Inspect the agent-bridge message cache (getCachedMessages export or a
 *      debug endpoint) — the tool_result block should be a {type:'text'}
 *      stub matching the format:
 *        `[Tool result cleared. Summary: ... . Full output retained as
 *         tool_call <id>.]`
 *   5. Inspect SQLite: tool_calls row for the same tool_call_id still has
 *      the full output_summary + output_artifact_id set.
 *   6. Send a second chat turn — the slice builder must not inject the full
 *      output, only the stub.
 *   7. Delete the project.
 */
test.skip(
  'phase 3 — oversized tool_result is replaced by a stub in later turns',
  async () => {
    // Intentionally empty. See the comment block above for manual steps.
  },
)
