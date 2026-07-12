#!/usr/bin/env bash
# ========================================================================
# validate_ci_versions.sh — Validate and normalize CI version inputs
#
# Usage:
#   validate_ci_versions.sh <source_version> <build_version>
#
# Inputs:
#   source_version   Palworld source version (latest, v1.0.0, 1.2.3-rc1)
#   build_version    Optional custom build version (defaults to source)
#
# Outputs (stdout, one key=value per line):
#   source_version
#   source_version_clean
#   source_version_base
#   build_version
#   build_version_clean
#   build_version_base
#
# Exit codes:
#   0  — validation passed, all outputs on stdout
#   1  — validation failed, error on stderr
# ========================================================================

set -o errexit
set -o nounset
set -o pipefail

SOURCE_VERSION_INPUT="${1:-}"
BUILD_VERSION_INPUT="${2:-}"

# ------------------------------------------------------------------
# Normalize source version
# ------------------------------------------------------------------
if [ -z "$SOURCE_VERSION_INPUT" ] || [ "$SOURCE_VERSION_INPUT" = "latest" ]; then
    SOURCE_VERSION="latest"
else
    SOURCE_VERSION="$SOURCE_VERSION_INPUT"
fi

# ------------------------------------------------------------------
# Normalize build version
# ------------------------------------------------------------------
if [ -n "$BUILD_VERSION_INPUT" ]; then
    BUILD_VERSION="$BUILD_VERSION_INPUT"
else
    BUILD_VERSION="$SOURCE_VERSION"
fi

# ------------------------------------------------------------------
# Validate version format
# ------------------------------------------------------------------
validate_version() {
    local input="$1"
    local label="$2"

    # "latest" is always valid
    if [ "$input" = "latest" ]; then
        return 0
    fi

    # Reject: whitespace, quotes, newlines, semicolons, backticks, $()
    # The regex intentionally contains literal shell metacharacters.
    # shellcheck disable=SC2016
    re_chars='[[:space:]]|["'\'';!`$(){}|&]'
    if [[ "$input" =~ $re_chars ]]; then
        echo "❌ ERROR: ${label}='${input}' contains shell metacharacters or whitespace." >&2
        echo "   Allowed: latest, v1, v1.0, v1.0.0, 1.0.0-beta, 1.0.0-rc1" >&2
        exit 1
    fi

    # Allow: v1, v1.2, v1.2.3, with optional -suffix (alphanumeric only)
    if echo "$input" | grep -qE '^[vV]?[0-9]+(\.[0-9]+)?(\.[0-9]+)?(-[a-zA-Z0-9]+)?$'; then
        return 0
    fi

    echo "❌ ERROR: ${label}='${input}' is not a valid version string." >&2
    echo "   Allowed: latest, v1, v1.2, v1.2.3, 1.0.0, 1.0.0-beta, 1.0.0-rc1" >&2
    exit 1
}

# Validate all non-"latest" versions
if [ "$SOURCE_VERSION" != "latest" ]; then
    validate_version "$SOURCE_VERSION" "source_version"
fi
if [ "$BUILD_VERSION" != "latest" ]; then
    validate_version "$BUILD_VERSION" "build_version"
fi

# ------------------------------------------------------------------
# Sanitize: single-line, no trailing whitespace
# ------------------------------------------------------------------
sanitize_output() {
    printf '%s' "$1" | tr -d '\n' | sed 's/[[:space:]]*$//'
}

SOURCE_VERSION="$(sanitize_output "$SOURCE_VERSION")"
BUILD_VERSION="$(sanitize_output "$BUILD_VERSION")"

# ------------------------------------------------------------------
# Process version strings for Docker tags
# ------------------------------------------------------------------
SOURCE_VERSION_CLEAN="${SOURCE_VERSION#v}"
BUILD_VERSION_CLEAN="${BUILD_VERSION#v}"

SOURCE_VERSION_BASE="${SOURCE_VERSION_CLEAN%%-*}"
BUILD_VERSION_BASE="${BUILD_VERSION_CLEAN%%-*}"

# ------------------------------------------------------------------
# Single-line output: one key=value per line
# ------------------------------------------------------------------
echo "source_version=${SOURCE_VERSION}"
echo "source_version_clean=${SOURCE_VERSION_CLEAN}"
echo "source_version_base=${SOURCE_VERSION_BASE}"
echo "build_version=${BUILD_VERSION}"
echo "build_version_clean=${BUILD_VERSION_CLEAN}"
echo "build_version_base=${BUILD_VERSION_BASE}"
