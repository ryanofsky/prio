# Priority bands

Bands are defined within a category. "P1 in wallet" says nothing about
how wallet work compares to validation work; there is no cross-category
ranking anywhere in this system.

**P1, category-critical.** Someone who cares about this category would
consider it seriously harmful for the underlying problem to stay
unresolved for another release cycle. Typical: correctness, security,
privacy, fund-safety, or reliability consequences; blocks a
category-defining project or several other important PRs; fixes an
important regression or supported-platform failure; requires a decision
that is preventing meaningful progress.

**P2, strategically important.** Substantial, durable value within the
category; deserves deliberate reviewer time. Delay is costly but not in
the way P1 delay is. Typical: meaningful user-facing improvements, major
maintainability improvements tied to concrete future work, important
performance gains, removal of a significant recurring burden.

**P3, worthwhile.** Clear use case and real value, reasonably deferrable.
Review is useful when someone is interested; it should not displace P1 or
P2 work just because it is smaller or more active.

**P4, marginal.** Narrow, cosmetic, speculative, redundant, or weakly
justified within this category. May be perfectly mergeable and useful;
has no special claim on scarce review attention.

**Unranked.** Too little context, too new, unclear intent, or low
confidence in the assessment. Shown last, with the reason.

There is no P0. Release urgency and public security severity are separate
flags, not a band, so that importance and immediacy are not confused.

## What goes with the band

- A **score** in [0, 1] consistent with the band (P1 0.75–1, P2 0.5–0.75,
  P3 0.25–0.5, P4 0–0.25). It orders PRs within a band and shades the
  table cell; it is never shown as a number.
- A **reason tag** of one or two words saying why the band applies, shown
  next to it in the cell: "bug fix", "fund safety", "DoS protection",
  "speedup", "new feature", "unblocks #N", "user request", "cleanup",
  "test coverage", "platform fix". Pick the single strongest reason.
- A **rationale** citing the evidence, shown on expand.
