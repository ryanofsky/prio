# Agreement

One question: can this change be merged once the code has enough review
and is bug free? "Positive" does not mean everybody likes it. It is fine
to merge a PR not everybody likes, as long as enough people want it and
nobody blocks it.

The scale is deliberately biased toward the positive end. People who
disagree with a PR are expected to say so clearly; silence is read as
consent. The one-word state is a summary, and the detail next to it must
describe the real situation ("Positive, but sipa sees X as a drawback and
the author declined to change it").

Inputs are the review vocabulary (Concept ACK, Approach ACK, ACK, Tested
ACK, NACK, Concept NACK, Approach NACK), the substance behind those words,
and objections raised without a verdict word. Nobody's opinion is weighted
by who they are.

## States

| State | Meaning |
|-------|---------|
| **Crickets** | Nobody has commented on the PR as a whole: no reviews, no concept comments. Nits and bot output do not count. |
| **Neutral** | Nobody has spoken for the PR, and an objection was raised and then settled. |
| **Positive** | The default once anyone has substantively commented and no objection holds the state lower. One "looks good" without much substance is enough. |
| **Strong** | At least one reviewer wants the PR for a specific stated reason, and nobody objects. Others merely affirming keeps it Strong. |
| **Positive w/ caveats** | Support with a standing, acknowledged drawback: someone says the change is a net negative for stated reasons but will not oppose it if others want it, or an objection was settled by agreeing to disagree rather than by a fix, so the harm remains valid and the PR can still move forward. |
| **Mild** | An objection that only needs an answer has none yet, or its critic pushed back on the answer; or an objection that needs a change was answered without one and the critic has not responded. Also the state when nobody has spoken for the PR and such an objection stands. |
| **Disputed** | An objection that needs a change was answered without one, and the critic pushed back. |
| **Blocked** | An objection that needs a change, and nobody has replied to it. Temporary: a PR moves out of Blocked when someone answers, and eventually merges with objections fixed or accepted, or closes. |

A "harm" is a concrete cost of merging: a bug, a regression, a security
or privacy weakening, a maintenance burden, a wrong interface, a
violation of a project policy. "I don't find this useful" or "not worth
review time" is not a harm; it is recorded as a suggestion, which needs
an answer before merging but leaves the state where it was. Suggestions
and questions never move the state.

## What an objection needs, and where it stands

Every objection needs a response before merging. It says which kind:

- **Blocked until answered** (the default): a direct reply deals with
  it, whether the reply agrees, explains, or declines.
- **Blocked until changed**: only a push that implements it, or the
  critic dropping it, deals with it. A defect that has to be fixed (a
  bug, a regression, a policy violation) needs a change; so does an
  objection whose critic says the PR should not merge as it is. A
  rejection stated without the word NACK ("this cannot be merged", "I
  don't think this should go in") is still one, and from a maintainer it
  is explicit.

Where it stands: **open** (nobody has replied directly; a reply that
only defers, "will look into it", leaves it open), **answered** (a
direct reply by the author or anyone else, whether or not the critic
has reacted), **fixed** (a push implements it), **accepted** (the critic
said the answer or fix is fine, or dropped it), **contested** (the critic
pushed back after the reply), **agreed to disagree**. The critic does not
have to withdraw formally: an answer the critic does not respond to
counts as answered. Approval by another reviewer does not answer an
objection.

| Objection needs | open | answered | contested | fixed or accepted | agreed to disagree |
|---|---|---|---|---|---|
| a change | Blocked | Mild | Disputed | settled | Positive w/ caveats |
| an answer | Mild | settled | Mild | settled | Positive w/ caveats |

The state is set by the hardest objection that is not settled. Once
nothing holds it lower, the state is Positive, Strong, or Neutral as the
support decides, or Positive w/ caveats when an objection was settled by
agreeing to disagree; the detail then names the standing drawback.

## Which error to prefer

Reporting more agreement than exists, by leaving out an objection
someone made, is the worse error: the reader has no citation to check
and would have to read the whole thread to notice. Over-weighting a
minor objection, or missing that one was settled, is the lesser error:
the quote is next to the state and can be checked in seconds. When in
doubt, list the objection and let the detail carry the doubt.

## Other rules

- Stale ACKs still count toward Agreement (the project wanted the change
  when it was reviewed); they do not count in the Reviews column.
- Disagreement about naming, style, or how commits are split or
  ordered is not disagreement about the change.
- Approvals with no rationale from accounts with no history in the
  project are not evidence of support.

## What the detail must contain

Next to the state: who raised what, in one clause each, and its status.
Examples: "Positive, but ajtowns thinks the option name is a footgun;
author disagrees, no follow-up." "Blocked: gmaxwell says the fee logic
can strand funds; author has not replied since 2026-04."
