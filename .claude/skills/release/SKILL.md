---
name: release
description: Run the release process — bump version, review staged changes, and summarize
disable-model-invocation: false
---

# Release Process

When the user says "do a release" (or similar), follow these steps:

1. **Check for uncommitted changes** — run `git status`. If there are any
   uncommitted or unstaged changes, **stop and ask the user** to commit or
   stash them before proceeding. Do NOT continue with a dirty working tree.
2. **Run the release script** — execute `scripts/release.sh`.
3. **Review staged files** — run `git diff --staged` and `git status` to
   inspect every changed file.
4. **Summarize the changes** — present two sections:
   - **Detailed explanation** — describe each change thoroughly (what
     changed, why it matters, any side effects).
   - **Brief bullet list** — one bullet per change, **max 20 words each**,
     giving a concise at-a-glance summary.
