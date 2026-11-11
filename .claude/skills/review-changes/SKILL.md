---
name: review-changes
description: Get an independent review of uncommitted changes from the reviewer persona, with proposed fixes and weak spots. Use after making changes and before committing, or when asked to review the current changes.
---

# Review changes

1. Collect the change: `git status`, the diff of tracked files against `HEAD` (staged and unstaged), and the full content of any new untracked files. If there is nothing to review, say so and stop.
2. Hand the change to the **reviewer** persona as a separate agent. Give it the diff, the new files, and a one-paragraph summary of what the change is meant to do. If your tool can't run a separate agent, do the review yourself following `reviewer`'s instructions, and say so.
3. Check each finding against the code before passing it on. Drop any that are wrong, and say which and why.
4. Present the findings ranked by severity: **must fix** first, then **suggestions**, each with its file, line and proposed fix.
5. Don't apply fixes yourself. Ask which ones to apply, then make those changes and run the tests (commands are in the repo's AGENTS.md).
6. Don't commit. When the user is happy, they commit, or ask you to with the `commit` skill.
