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

```
python3 -m prio.cli --config ../prio-bitcoin extract \
    --backup /var/lib/github-metadata-backup/data/bitcoin/bitcoin \
    --out /var/lib/prio/extract
```

Requires Python 3.11+. The extract stage has no dependencies beyond the
standard library.

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
