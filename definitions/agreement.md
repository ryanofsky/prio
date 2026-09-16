# Agreement

One question: does the project want this change?

Inputs are the review vocabulary (Concept ACK, Approach ACK, ACK, Tested
ACK, NACK, Concept NACK, Approach NACK), the substance behind those words,
and objections raised without a verdict word. Counts alone do not decide
the state; substance does. Nobody's opinion is weighted by who they are.

| State | Meaning |
|-------|---------|
| **Strong** | Substantive support and no pushback. One enthusiastic reviewer with a real rationale and nobody objecting counts: people who disagree are expected to speak up. |
| **Mild** | Support alongside mild, substantive objections. Reservations have been stated but nobody claims the change is a net negative. |
| **Disputed** | Objections point at bigger harms or possible harms, or reviewers disagree about whether the change is a net positive. The default once opposition is more than mild. |
| **Blocked** | Harms have been pointed out and the author has not seriously responded to or addressed them. A temporary state: a PR moves between Disputed and Blocked, or Mild and Blocked, as concerns are raised and addressed, and eventually merges with objections fixed or accepted, or closes. |
| **Crickets** | No substantive signal either way: no reviews, or only nits and bot output. |

Judgment calls:

- Concept ACKs with nothing behind them ("Concept ACK" and nothing else)
  are weak evidence of support; several of them without objection still
  reach Strong, because silence from those who might object is itself a
  signal.
- Stale ACKs still count toward Agreement (the project wanted the change
  when it was reviewed); they do not count toward the Reviews column.
- An objection that the author addressed in a later push, with the
  objector silent afterwards, is treated as resolved.
- Disagreement about naming, style, or commit structure is not
  disagreement about the change.

The reason for the state is always shown next to it, with links to the
comments it rests on.
