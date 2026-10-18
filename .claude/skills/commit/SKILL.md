---
name: commit
description: Create a git commit following Recipe Hub conventions. Use when asked to commit, to stage and commit, or to record work in git.
---

# Commit

1. Check `git status` and the diff. If the changes mix unrelated concerns, split them into separate commits.
2. Run the project's tests and linters (commands are in the repo's AGENTS.md). Don't commit failing code unless asked to.
3. Stage explicit paths. Never stage secrets, `.env` files, build output or caches.
4. Write a title-only Conventional Commits message:
   - Format: `type(scope): summary`. The scope is optional, e.g. `i18n`, `recipes`, `auth`.
   - Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `build`, `ci`, `perf`.
   - Imperative mood, lowercase after the colon, no trailing period, at most 72 characters.
   - No body, no trailers, no attribution footer.
5. Commit, then show the resulting `git log --oneline -1`.
