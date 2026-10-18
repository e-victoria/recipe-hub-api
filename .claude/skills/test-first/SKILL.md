---
name: test-first
description: Write failing unit tests for a planned change to app behaviour before implementing it, using the test-author persona. Use before adding a feature, changing behaviour or fixing a bug, or when asked to write tests first.
---

# Test first

1. Pin down the planned change in a few sentences: the behaviour to add or change, inputs and outputs, edge cases and failure paths. If something is ambiguous, ask before writing tests. Pure refactors and changes with no behaviour (styling, docs, config) don't need this skill; say so and continue.
2. Hand that specification to the **test-author** persona as a separate agent, along with the files the change will touch. If your tool can't run a separate agent, write the tests yourself following `test-author`'s instructions, and say so.
3. Check what it wrote:
   - The tests cover the behaviour in the specification, including the edges, and test it through the public surface (see the `write-tests` skill).
   - New tests fail for the right reason (missing behaviour), not because of syntax or import errors.
   - Existing tests still pass, and no production code was changed.
4. Show the user the list of tests, what each checks and its current state, and confirm they match the intended behaviour before implementing.
5. Then implement the change until the new tests pass. Change a test only if it was wrong, and say so.
