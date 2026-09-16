# Reviewability

One question: if I review this PR right now, is my work likely to be
wasted by changes that are already known to be coming?

This is about the code, not about whether the project wants the change.
Concept agreement is not a prerequisite for code review here.

| State | Meaning |
|-------|---------|
| **Ready** | Nothing known is about to invalidate a review. |
| **Stale** | Mechanical blockers: needs rebase, CI failing, or the author has been silent for a long time (`stale_author_silent_days` in project.toml). |
| **Paused** | A question or request that would materially change the PR, and so invalidate review of the current code, has been open for `waiting_on_author_days` (default 7) without an author response. The UI may show a more specific phrase in the Paused color, such as "Waiting on author". |

Judgment calls:

- **Draft is a weak signal.** A draft often means "don't merge yet" or
  "this sits on another PR", not "don't review". Do not mark a PR Paused
  because it is a draft.
- **Stacked PRs.** A PR based on another open PR is reviewable if its base
  is reviewable. Reviewers will often prefer to start at the base, but
  they do not have to wait for it to merge.
- **Not every unanswered comment pauses a PR.** A nit, a question the
  reviewer answered themselves, or a request the author already addressed
  in a push does not. The request has to be material and still open.
- **Author said "wait".** "Reworking this", "don't review until X lands",
  "will rebase after Y" are Paused with that reason, regardless of days.

The reason for a non-Ready state is always shown next to it.
