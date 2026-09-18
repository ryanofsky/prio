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

Claims. One entry per objection: a concern that, if right, argues
against merging as-is (design, safety, scope, correctness, approach,
interface, maintenance, usefulness, style). Record the concrete harm it
names, a short quote, its kind, whether the reviewer treats it as a
reason not to merge (a NACK word is not required; "this seems backwards
to me", "I don't think this should go in", "potential footgun" from a
maintainer are rejections), the ids of the author's replies to it, and
its status:

- open: not settled;
- resolved: a fix was pushed and the reviewer did not object again, or
  the author rejected it with a rationale and the reviewer did not push
  back, or the reviewer withdrew it;
- agreed_to_disagree: both accept the PR can proceed with the harm
  standing.

For anything not open, give the id and a short quote of the statement
that settled it. A push is not a reply and does not by itself settle a
claim; an agreement in principle without a pushed fix leaves it open;
approval by another reviewer does not answer it; check dates.

When unsure whether a statement is an objection, list it. A listed
non-objection carries a quote a reader can check in seconds; an omitted
objection leaves nothing to check. Concerns phrased tentatively by an
experienced reviewer ("this breaks my security assumptions", "I'm not
sure this was a good idea") are claims with a harm. A question the
author answered is not a claim; an inline code question with no named
harm is a question; a bug report inside an ACK review is a claim by a
supporter, open until fixed, not blocking unless they say so; style
and naming disagreements are not claims about the change.

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
given (reviewers and commenters; never the PR author), with a stance: objection if any of their statements names a cost
of merging (then it must appear in claims), support if they spoke for
the change, question if they only asked and were answered, neutral for
nits, process, or off-topic. Fill this first; it is the checklist.

Some entries in the record are marked PINNED: a person set that status.
Do not change a pinned status unless a statement dated after the pin
settles or reopens it, and say so in the notes.

Return the full record: participants, claims, support, waiting_on, and
notes (one or two sentences on what changed and anything you were unsure
about).
