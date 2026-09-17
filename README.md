# prio

Lists a project's open pull requests by category, ranked within each
category by how much the problem they address matters, so that a PR
that is a priority within its area is not overlooked because it is
quiet, large, or old. "prio" is short for priority: priority within a
category, never across categories. There is deliberately no global
list; the only entry point is a category.

A language model does the categorizing and ranking against written
category definitions and shared definitions of importance, review state,
and agreement. Every judgment on the site is labeled as model output
and shown with its reasoning and inputs one click away. It is an
unofficial tool and does not speak for the project it covers.

This repository is the engine: code, prompts, shared definitions, site
rendering, and deployment modules. What the site *contains* for a given
project lives in a separate config repo, e.g.
[prio-bitcoin](https://github.com/ryanofsky/prio-bitcoin) for Bitcoin
Core, which is served at https://prio.ofsky.org. Discussion about how the
site works belongs here; discussion about categories and rankings
belongs in the config repo.

## Data source

A [github-metadata-backup](https://github.com/0xB10C/github-metadata-backup)
directory: one JSON file per issue and PR with the full timeline. For
diffs, a local clone of the project fetches each open PR's head. The
engine never calls the GitHub API for PR content.

## Pipeline

| Stage | Command | Model call? | Output |
|-------|---------|-------------|--------|
| git | `prio git` | no | per-PR changed files, per-commit stats, a budgeted patch |
| extract | `prio extract` | no | `prs/<n>.json`, `index.json`: metadata, ACK table, staleness signals, stack edges, linked issues, discussion text, an input hash |
| dossier | `prio dossier` | yes, per PR when its input hash changes | summary, discussion state, reviewability, agreement, per-category band and score |
| display | `prio display` | yes, per dossier, small | the short lines the table shows |
| rank | `prio rank` | yes, per category, on demand or weekly | bands checked against each other, order, review-chain notes |
| render | `prio render` | no | static site: category pages, per-PR pages, ranking notes, raw JSON |

Model stages go through the Batch API by default (half price, results
within hours) and store every result with its model, token usage, and a
cost estimate. `nix/prio-pipeline.nix` runs the whole thing on a
schedule as a NixOS service.

Requires Python 3.11+. The extract and render stages have no
dependencies beyond the standard library; the model stages need the
`anthropic` package. `nix-shell` in this directory provides both and
defines a `prio` command (see `shell.nix`). Set `PRIO_CONFIG` to a config
repo checkout to omit `--config`.

## Usage

### Extract

```
prio --config ../prio-bitcoin extract \
    --backup /var/lib/github-metadata-backup/data/bitcoin/bitcoin \
    --out /var/lib/prio/extract [--only 123,456]
```

Writes `prs/<n>.json` and `index.json`. Fast (seconds), no model.

Pass `--refs-index FILE` so numbers mentioned in PRs resolve to a type,
state, merge date, and title. Build the file from a full backup with
`scripts/refs-index.sh BACKUP_DIR > refs-index.tsv` (one awk pass, seconds
for 35k files).

### Dossier

Credentials: `ANTHROPIC_API_KEY` in the environment, or a key in
`~/.config/prio/api-key` (mode 600), which the CLI reads if the variable
is unset. Use a key from a workspace with a monthly spend limit.

```
# 1. See what it would cost before spending anything. Counts tokens for
#    every PR, prints an estimate, and shows one full prompt.
prio dossier submit --extract EXTRACT --out DOSSIER --only 123,456 --dry-run

# 2. Submit through the Batch API (half price; results usually within an
#    hour, up to 24 h). Only PRs whose input hash has no dossier yet are
#    sent; --force re-assesses anyway.
prio dossier submit --extract EXTRACT --out DOSSIER [--only ...] \
    [--model claude-opus-5] [--effort high] [--budget-tokens 40000]

# 3. Check on it any time, from any terminal. Reads the local manifests in
#    DOSSIER/batches/ and asks the API for their status. --all also lists
#    batches on the workspace that have no local manifest.
prio dossier status --out DOSSIER [--all]

# 4. Fetch results once the status is "ended". Safe to rerun; a manifest is
#    marked collected only after its results are written.
prio dossier collect --out DOSSIER [--batch msgbatch_...] [--wait]

# Small iterations: call the API directly instead of batching (full price,
# minutes instead of hours).
prio dossier submit --extract EXTRACT --out DOSSIER --only 123 --sync
```

A batch lives on Anthropic's side once submitted. Killing the local
process loses nothing; rerun `collect` later. Results stay available for
29 days. Each dossier is stored as `DOSSIER/<n>/<input-hash>.json` with
the model, token usage, and a cost estimate; `DOSSIER/<n>/latest` names
the current one. Batch manifests under `DOSSIER/batches/` record what was
sent and, after collection, what it cost.

### Rank

```
prio rank --extract EXTRACT --dossier DOSSIER --display DISPLAY --out RANK [--category ipc] [--model claude-opus-5] [--dry-run] [--force]
prio render ... --rank RANK
```

One call per category with every member PR's card. Skips a category
whose members and dossiers are unchanged since its last ranking.

**How ranking combines with daily assessments.** Dossiers give each PR a
band and a score judged alone. A ranking pass gives the PRs of one
category consistent bands and an order judged together. The renderer
merges them per category:

- A ranking entry applies only while the dossier it saw is unchanged
  (the ranking file records each dossier's input hash).
- Ranked PRs keep the pass's band and relative order.
- A PR the pass did not see, or whose dossier changed since, uses its
  own band and is slotted among the ranked PRs of that band by score.

So the order is stable between passes and daily arrivals are interleaved
rather than appended. A band the pass changed is shown with its reason in
the priority cell; the pass's notes on review order and overlapping PRs
are on `rank/<category>.html`, linked from the legend.

### Report

```
prio report --extract EXTRACT --dossier DOSSIER [--category ipc] [--no-expand] > report.md
```

One markdown table per category sorted by score, with an expanded block
per PR (summary, rationale, evidence, reviewability and agreement
reasons, dependencies, uncertainties, card).

## Layout

```
prio/            Python package
  extract.py     stage: backup JSON -> compact facts
  gitdata.py     sidecar: PR heads, file lists, patches from a local clone
  dossier.py     stage: per-PR assessment (Batch API)
  display.py     stage: short table lines from a dossier
  rank.py        stage: per-category listwise pass
  render.py      stage: static site
  acks.py        ACK/NACK vocabulary parser (cross-check for adapters)
  adapters/      parsers for project bots (drahtbot)
  categories.py  category files and pre-filter hints
  config.py      project.toml loader
  prices.py      list prices for cost estimates
definitions/     shared definitions used in every prompt and shown on the site
  priority.md    what makes a PR important
  bands.md       P1–P4
  reviewability.md
  agreement.md
prompts/         prompt text for the dossier, display, and rank stages
nix/             NixOS module: services.prio (daily pipeline, weekly ranking)
scripts/         refs-index.sh (resolves cited PR/issue numbers from a full backup)
```

## Config repo schema

`project.toml` in the config repo:

```toml
[project]
name = "Bitcoin Core"
site_title = "..."
orgs = ["bitcoin", "bitcoin-core"]   # members may submit feedback via the site

[[repos]]
owner = "bitcoin"
repo = "bitcoin"

[bots]
logins = ["DrahtBot"]                # treated as bots
adapters = ["drahtbot"]              # engine adapters to run

[size]                               # added+deleted lines
small = 100
medium = 400
large = 1000

[reviewability]
waiting_on_author_days = 7
stale_author_silent_days = 60
```

`categories/<name>.md`: front matter with `title`, `owner`, and
pre-filter hints (`labels`, `paths`, `keywords`), then two sections: what
the category covers, and what counts as important within it.

`feedback/prs/<n>/<timestamp>-<login>.md` and
`feedback/categories/<name>/<timestamp>-<login>.md`: one entry per file,
front matter `author`, `author_id`, `date`, `pr`, `category`, `kind`
(`fact` or `opinion`), `head`, `via`, then the text.
