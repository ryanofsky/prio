# Reviewability

One question: if I review this PR right now, is my work likely to be
wasted by changes that are already known to be coming?

This is about the code, not about whether the project wants the change.
Concept agreement is not a prerequisite for code review here.

| State | Meaning |
|-------|---------|
| **Ready** | Nothing known is about to invalidate a review. |
| **Stale** | Mechanical blockers: needs rebase, CI failing, or the author has been silent for a long time (`stale_author_silent_days` in project.toml). |
| **Paused** | A question or request that would materially change the PR, and so invalidate review of the current code, has been open for `waiting_on_author_days` (default 7) without an author response. Also: the author has said to wait. |

Each state comes with a short label for the table cell, at most four
words, specific enough to stand alone. Good: "Ready", "Needs rebase",
"CI failing", "Review #35675 first", "Waiting on author", "Author
reworking". Bad: "Author says wait / based on unmerged upstream". When a
PR number explains the state, put it in the label. The full reason goes
in the detail.

Judgment calls:

- **Draft is a weak signal.** A draft often means "don't merge yet" or
  "this sits on another PR", not "don't review". Do not mark a PR Paused
  because it is a draft.
- **Stacked PRs.** A PR based on another open PR is reviewable if its base
  is reviewable. Reviewers will often prefer to start at the base, so the
  label may say "Review #N first", but that is guidance, not a block.
- **Not every unanswered comment pauses a PR.** A nit, a question the
  reviewer answered themselves, or a request the author already addressed
  in a push does not. The request has to be material and still open.
- **Author said "wait".** "Reworking this", "don't review until X lands",
  "will rebase after Y" are Paused with that reason, regardless of days.

The reason for a non-Ready state is always shown next to it.
