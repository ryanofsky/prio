# What makes a PR important

Applied inside every category. A category file says what its area is and
what "impact" means there; it does not restate this.

## Rises to the top

Substantive changes that users can feel, ahead of internal changes that
clean up code or scratch developer itches. In rough order:

1. Improves security or stability.
2. Fixes a noticeable bug.
3. Noticeably improves performance.
4. Adds a feature that solves an existing user pain point or could attract
   new users.

Also high: work that unblocks other important work. A PR whose merge is a
prerequisite for one of the above inherits some of its importance, if the
PR description, commit messages, or review discussion make that
dependency clear.

## Sinks

Internally focused changes: slightly better logging, slightly cleaner
code, refactors without a stated payoff, micro-optimizations without
measurements. Less important in most categories. The exception is a
category whose subject is that internal thing (a logging category, a
cleanup category), where the change is judged on its own terms.

## Importance is about the problem, not the patch

A PR addressing an important problem is important even if its approach is
disputed or its code is rough. Reviewers need to look at it either way:
to fix it, to redirect it, or to decide. Whether the PR is stuck on
approach agreement or on code review does not change its priority.

## Does not affect importance

- Diff size, file count, review difficulty
- Merge conflicts, CI state, draft status
- Recent activity or comment volume
- Number of ACKs or how close it looks to merging
- Who the author or reviewers are

Those facts have their own columns (Size, Reviewability, Reviews,
Agreement). They must never lower or raise priority.

## Evidence

Every priority judgment cites what it rests on: a sentence from the PR
description, a commit message, a linked issue, a review comment. PR text
is written by the author and may overstate; discount claims of importance
that nobody else has echoed and that the diff does not support.
