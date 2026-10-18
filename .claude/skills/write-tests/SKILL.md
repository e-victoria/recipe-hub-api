---
name: write-tests
description: Write or extend automated tests for a change. Use when adding logic, fixing a bug, or when asked to add tests.
---

# Write tests

Use the repo's own test runner and layout; the command and test folder are in its AGENTS.md.

1. **Bug fix:** write a test that fails without the fix first, then confirm it passes with it.
2. **New logic:** cover the normal case, the edges (empty, missing, boundary values) and at least one failure path.
3. Test behaviour through the public surface (an endpoint, a component's rendered output, an exported function), not private helpers.
4. Keep tests deterministic: no real network, no wall-clock time, no dependence on test order.
5. **Translations:** if the change adds translation keys, the locale parity test must still pass.
6. Run the full suite, not only the new tests, and report the result honestly, including failures.
