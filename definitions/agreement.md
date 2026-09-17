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
| **Neutral** | Nobody has spoken for the PR, and a nonblocking criticism was raised and then resolved. |
| **Positive** | The default once anyone has substantively commented and there is no unresolved criticism. One "looks good" without much substance is enough. |
| **Strong** | At least one reviewer wants the PR for a specific stated reason, and nobody objects. Others merely affirming keeps it Strong. |
| **Positive w/ caveats** | Support with a standing, acknowledged drawback: someone says the change is a net negative for stated reasons but will not oppose it if others want it, or a criticism was resolved by agreeing to disagree rather than by a fix, so the harm remains valid and the PR can still move forward. |
| **Mild** | A criticism pointing at a real harm the PR would cause if merged is unresolved, and the critic treats it as nonblocking. Also the state when nobody has spoken for the PR and such a criticism is open. |
| **Disputed** | An unresolved criticism that the critic treats as blocking, with the author engaging. |
| **Blocked** | A blocking criticism the author has not responded to. Temporary: a PR moves between Disputed and Blocked as the author answers, and eventually merges with objections fixed or accepted, or closes. |

A "harm" is a concrete cost of merging: a bug, a regression, a security
or privacy weakening, a maintenance burden, a wrong interface. "I don't
find this useful" or "not worth review time" is not a harm; it leaves
the state where it was.

## When a criticism is resolved

Resolved:

- The author rejects it with a rationale and the critic does not push back.
- The author and critic agree to disagree and the PR can move forward.
- The author proposes a fix and implements it.

Not resolved:

- The author proposes a fix, or agrees in principle, and has not
  implemented it.
- The author asks the critic a question and the critic has not answered.
- The author has not responded at all.
- Another reviewer approved; approval by someone else does not answer an
  objection.

The state is set by the hardest objection still open. A rejection
stated without the word NACK ("this cannot be merged", "I don't think
this should go in") is still a rejection, and from a maintainer it is
blocking.

When a resolved criticism was the only thing holding the PR at Mild or
Disputed, the state returns to Positive, Strong, or Neutral as
appropriate; if it was resolved by agreeing to disagree rather than by a
fix, the state is Positive w/ caveats, and the detail names the standing
drawback. If the critic is unsatisfied with the answer and decides the
PR should not merge, Mild becomes Disputed.

## Which error to prefer

Reporting more agreement than exists, by leaving out an objection
someone made, is the worse error: the reader has no citation to check
and would have to read the whole thread to notice. Over-weighting a
minor objection, or missing that one was resolved, is the lesser error:
the quote is next to the state and can be checked in seconds. When in
doubt, list the objection and let the detail carry the doubt.

## Other rules

- Stale ACKs still count toward Agreement (the project wanted the change
  when it was reviewed); they do not count in the Reviews column.
- Disagreement about naming, style, or commit structure is not
  disagreement about the change.
- Approvals with no rationale from accounts with no history in the
  project are not evidence of support.

## What the detail must contain

Next to the state: who raised what, in one clause each, and its status.
Examples: "Positive, but ajtowns thinks the option name is a footgun;
author disagrees, no follow-up." "Blocked: gmaxwell says the fee logic
can strand funds; author has not replied since 2026-04."
