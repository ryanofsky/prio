# Ledger schema history

What each version of the PR record changed, and what data read under an
older version may lack or get wrong. Two markers say where older data
remains:

- `processed.schema_floor` (per record): the oldest schema any of the
  record's statements was read under. A seed or a re-read of the whole
  thread sets it to the current schema; an incremental read, which sees
  only new statements, leaves it. Below the current schema, the record may
  be missing items the older rules did not record.
- `from_schema` (per claim): the schema under which the item was last
  checked against its statement. A seed or re-read that returns the item
  sets it to the current schema; an incremental read keeps it, since the
  model sees only the item's quote there, not the statement.

`ledger update` re-reads records below the current schema within a daily
budget (`--reread-budget`, `PRIO_REREAD_BUDGET` in ledger-run.sh):
first those in the top five of any category on the last render, then
those with new statements. A re-read sends the whole thread and the
current record, plus the "Re-check" list of every version the record is
behind.

The "Re-check" sections are given to the model verbatim. Keep them short,
and phrase each point as something to check, not something to change.

## Schema 2 (2026-09-24)

Claims became items a reviewer raised that need a response: `type`
objection (one harm), suggestion (a request, no harm), or question;
`clears_with` answer or change replaced `blocking`; `status` open,
answered, fixed, accepted, contested, or agreed_to_disagree replaced
open/resolved/agreed_to_disagree plus `after_reply`; `status_by` replaced
`settled_by`; `part` numbers several items from one statement. Design:
claims-redesign.md in the notes repo. Records were migrated without a
model call (`ledger.upgrade_v1`).

### Re-check (data read under schema 1)

Items carried over from schema 1 are all objections, converted
mechanically. For each existing item, check against its statement:

- Does it name more than one harm? Keep the first as this item and give
  each further harm its own item with the next `part`.
- Is it really a suggestion (asks for something, names no cost of
  merging) or a question (asks for information)? Change its type.
- A `usefulness` objection whose harm is only that the change is not
  worth having: is it a suggestion instead?
- Marked answered with the note "reply on record; standing not assessed
  yet": is the reply a direct answer, or only a deferral ("will look into
  it"), which leaves it open?
- Does `clears_with` fit: change only for a defect that has to be fixed or
  a reviewer saying the PR should not merge as it is?

Then check every statement for suggestions and questions that are not
recorded yet; schema 1 did not record them.

## Schema 1 (2026-09-17)

The first ledger record: participants, claims (objections with a harm,
`blocking`, status open/resolved/agreed_to_disagree, later `after_reply`),
support, waiting_on.
