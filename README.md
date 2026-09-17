# prio

A category-scoped review-priority map for GitHub pull requests. Open PRs
are sorted into categories (for Bitcoin Core: validation, p2p, wallet,
ipc, ...) and ranked within each category by how important the problem
they address is, so that scarce review time goes to consequential work
rather than to whatever is most active. A model does the categorizing and
ranking against version-controlled definitions; every judgment is labeled
as model output with its rationale and inputs exposed.

There is deliberately no global list. The only entry point is a category.

This repository is the engine: code, prompts, shared definitions, site
templates, deployment modules. What the site *contains* for a given
project lives in a separate config repo, e.g.
[prio-bitcoin](https://github.com/ryanofsky/prio-bitcoin) for Bitcoin
Core. Discussion about how the site works belongs here; discussion about
categories and rankings belongs there.

## Data source

A [github-metadata-backup](https://github.com/0xB10C/github-metadata-backup)
directory: one JSON file per issue and PR with the full timeline. The
engine never calls the GitHub API for PR content.

## Pipeline

| Stage | Command | Model? | Output |
|-------|---------|--------|--------|
| extract | `prio extract` | no | `prs/<n>.json`, `index.json`: metadata, ACK table, staleness signals, stack edges, linked issues, discussion text |
| dossier | (not yet) | yes, per PR when its input changes | summary, discussion state, reviewability, agreement, per-category factor scores |
| rank | (not yet) | yes, per category, weekly | bands and order within each category |
| merge | (not yet) | no | site data |
| render | (not yet) | no | static HTML |

Requires Python 3.11+. The extract stage has no dependencies beyond the
standard library; the model stages need the `anthropic` package.
`nix-shell` in this directory provides both and defines a `prio` command
(see `shell.nix`). Set `PRIO_CONFIG` to a config repo checkout to omit
`--config`.

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
  extract.py     stage 1
  acks.py        ACK/NACK vocabulary parser (cross-check for adapters)
  adapters/      parsers for project bots (drahtbot)
  config.py      project.toml loader
definitions/     shared definitions used in every prompt and shown on the site
  priority.md    what makes a PR important
  bands.md       P1–P4
  reviewability.md
  agreement.md
prompts/         prompt templates (stage 2 and 3)
nix/             NixOS modules for running the pipeline and serving the site
site/            templates and CSS
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
