#!/usr/bin/env bash
# Select the newest semver-like tag before the current release tag.
#
# Usage:
#   find_previous_release_tag.sh <current_tag>
#
# Non-release tags such as `latest` are ignored. A leading `v` is ignored
# while comparing versions, but the original tag spelling is returned.

set -euo pipefail

CURRENT_TAG="${1:-}"
CURRENT_TAG_NORMALIZED="${CURRENT_TAG#v}"
CANDIDATES=""

is_release_tag() {
    [[ "$1" =~ ^[vV]?[0-9]+(\.[0-9]+){0,2}(-[0-9A-Za-z.-]+)?$ ]]
}

while IFS= read -r tag; do
    normalized="${tag#v}"

    if [ "$normalized" = "$CURRENT_TAG_NORMALIZED" ]; then
        continue
    fi

    if is_release_tag "$tag"; then
        CANDIDATES+="${normalized}"$'\t'"${tag}"$'\n'
    fi
done < <(git tag --merged HEAD --list)

if [ -n "$CANDIDATES" ]; then
    printf '%s' "$CANDIDATES" | sort -t $'\t' -k1,1V | tail -n 1 | cut -f2-
fi
