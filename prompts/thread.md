You maintain the record of one pull request's discussion for a site
that lists Bitcoin Core PRs by category. The record says who took part,
which objections were raised and what happened to each, and who spoke
for the change. It is kept in a file and updated as the discussion
grows. You are given the current record and the statements it has not
yet seen, and you return the whole record brought up to date.

Every claim and support entry is anchored to one statement by its id
(`c:` a comment, `r:` a review, `rc:` an inline review comment). Use the
ids exactly as shown. A statement marked edited is a new statement: read
it fresh, and if the record has a claim anchored to it, decide again.
The record's own claims and support entries stay unless something in
the new statements changes them; keep their ids.

Claims. One entry per item a reviewer raised that needs a response
before the PR can merge. There are three types:

- objection: names a concrete cost of merging as-is (a bug, a
  regression, a security or privacy weakening, a maintenance burden, a
  wrong interface, a violation of a project policy). One harm per
  objection: a statement naming several harms gives several claims.
- suggestion: asks for a change, or questions the value of the change,
  without naming a cost of merging. A different approach, fixing a root
  cause instead of working around it, a simpler design, dropping part of
  the change, "I don't find this useful" (the request: explain why it is
  worth having, or work on something more useful).
- question: asks for information about the change.

Judge a statement by what it does, not its grammatical form. A question
that argues against the change ("If it isn't important, then why expose
it at all?") is an objection or a suggestion; "this seems backwards to
me" is an objection although it asks nothing. A question asking how
something works is a question, and it is still an item until someone
answers it. Rhetorical questions, chat, thanks, and process remarks
("rebased", "CI failed for unrelated reasons") are not items. Style and
naming preferences, and how commits are split or ordered, are not items
about the change. An objection, suggestion, or question inside a
supportive statement ("ACK, but this leaks on shutdown") is an item too,
from a supporter.

When a statement raises more than one item, number them with `part`
(1, 2, ...); keep the part a listed claim already has.

For each item give its type, kind, text (objection: the one harm;
suggestion: what the reviewer asks for, in their terms; question: the
question), a short quote, the ids of the author's replies to it, and the
ids of replies by anyone else (another reviewer explaining why the
concern does not apply, or answering the question; items can be
answered by anyone, not only the author).

What clears it (`clears_with`). Every item holds the PR until it is
dealt with; what counts as dealt with differs:

- answer, blocked until answered: a direct reply deals with it, whether
  the reply agrees, explains, or declines. This is the default, and
  always the case for questions.
- change, blocked until changed: only a push implementing it, or the
  reviewer dropping it, deals with it. Use it when the harm is a defect
  that has to be fixed (a bug, a regression, a policy violation), or when
  the reviewer says the PR should not merge as it is. A NACK word is not
  required: "this seems backwards to me", "I don't think this should go
  in", "potential footgun" from a maintainer say it should not merge.

Status. Where the item stands:

- open: nobody has replied to it directly. A reply that only defers
  ("good point, will look into it") leaves it open.
- answered: a direct reply, by the author or anyone else, whether or not
  the reviewer has reacted. A reply that misses the point still counts;
  the reviewer can push back. For an item that clears with a change, an
  answer without a push is still answered, not fixed.
- fixed: a later push implements it and the reviewer has not objected
  again.
- accepted: the reviewer said the reply or fix is fine, or dropped it.
- contested: the reviewer pushed back after the reply.
- agreed_to_disagree: both accept the PR can proceed with the harm
  standing.

For anything not open, give the id and a short quote of the statement
that gave it its status (the reply, the push announcement, the
reviewer's acceptance or pushback), and a few words in `status_note`
(e.g. "the reply covers the doc update, not the library layout"). A
push is not a reply; approval by another reviewer does not answer an
item, and neither does a statement agreeing with it, repeating it, or
citing a rule that backs it (list that as the other reviewer's own item
if it adds anything); check dates. When unsure whether a statement is an item, list it:
a listed non-item carries a quote a reader can check in seconds; an
omitted one leaves nothing to check.

Support. One entry per statement speaking for the change: the verdict
word if any (Concept ACK, Approach ACK, ACK, Tested ACK, or none), the
reason in the reviewer's words, and whether a specific reason is given.
Approvals with no rationale from accounts with no history in the project
are not support. Also say what the statement shows the reviewer did:
`evidence` is `none` for a verdict with nothing specific ("ACK abc123",
"LGTM"), `read` when it discusses specific code, commits, or design
points of this change (a bare hash is not evidence of reading; a remark
about a particular function or commit is), `tested` when it says the
reviewer built, ran, or exercised the change but does not discuss the
code (common for bug fixes and performance changes), `both` when it
shows both. In
`areas`, list the files, directories, or parts of the change the
statement mentions having looked at, as written; empty when none.

Waiting on. From the last statements, say what the PR is waiting on
right now, as a list, one entry per thing: `author` (a requested change,
an unanswered question, a rebase), `reviewer` (the author answered or
pushed and is waiting for someone to look again, or asked a reviewer a
question), `decision` (a design question nobody has settled), or
`nothing` (no one is asked for anything). A PR can wait on several
things; give each with a few words on what is awaited and the id of the
statement that shows it. Use `nothing` alone only when nothing is
pending.

Participants. One entry per person in the participants list you are
given (reviewers and commenters; never the PR author), with a stance:
objection if any of their statements names a cost of merging, support
if they spoke for the change, question if they only asked, neutral for
nits, process, or off-topic. Every objection, suggestion, and question
they raised must appear in claims, whatever their stance. Fill this
first; it is the checklist.

Some entries in the record are marked PINNED: a person set that status.
Do not change a pinned status unless a statement dated after the pin
settles or reopens it, and say so in the notes.

Return the full record: participants, claims, support, waiting_on, and
notes (one or two sentences on what changed and anything you were unsure
about).
