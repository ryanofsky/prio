#!/usr/bin/env bash
# Build the reference index for `prio extract --refs-index`.
#
#   refs-index.sh BACKUP_DIR > refs-index.tsv
#
# BACKUP_DIR is a github-metadata-backup directory containing pulls/ and
# issues/. Output is one line per PR or issue: number, type (pull|issue),
# state, merged_at (empty if not merged), title. One awk pass over all
# files; on a full bitcoin/bitcoin backup (35k files, 3.4 GB) this takes
# well under a minute. Needs only awk and the backup's formatting: the REST
# object's own fields are the first ones at four-space indentation.
set -euo pipefail
dir=${1:?usage: refs-index.sh BACKUP_DIR}
for kind in pull issue; do
  find "$dir/${kind}s" -name '*.json' -print0 | xargs -0 awk -v kind="$kind" '
    function emit() {
      if (n != "" && title != "" && state != "")
        printf "%s\t%s\t%s\t%s\t%s\n", n, kind, state, merged_at, title
    }
    FNR == 1 { emit(); n = FILENAME; sub(/.*\//, "", n); sub(/\.json$/, "", n); title = ""; state = ""; merged_at = "" }
    /^    "title": /     && title == ""     { title = $0; sub(/^    "title": "/, "", title); sub(/",?$/, "", title) }
    /^    "state": /     && state == ""     { state = $0; sub(/^    "state": "/, "", state); sub(/",?$/, "", state) }
    /^    "merged_at": / && merged_at == "" { merged_at = $0; sub(/^    "merged_at": /, "", merged_at); sub(/,$/, "", merged_at); gsub(/"/, "", merged_at); if (merged_at == "null") merged_at = "" }
    END { emit() }
  '
done
