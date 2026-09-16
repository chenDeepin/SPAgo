#!/usr/bin/env bash
# Build the app image with a distinguishable build identity (B-34).
#
# Plain `docker compose up --build` works without this script: it injects the
# placeholder "unknown", which /healthz reports explicitly. But artifacts
# recorded from that image cannot be told apart — every build under one API
# version looks the same. This script computes the identity on the build host,
#
#   git describe --always --dirty   →   efb1357        (a clean checkout)
#                                      efb1357-dirty   (uncommitted changes)
#
# exports it as SPAGO_BUILD_ID, and builds through compose so the compose file
# stays the single owner of the image definition. The identity is baked into
# the image environment by docker/app/Dockerfile; the running container has no
# .git directory and never reads one.
#
# Failing to compute an identity fails the build: a distinguishable build is
# this script's entire job, and a guessed identity would be worse than none.
#
# Usage: scripts/build_app.sh [extra docker compose build flags, e.g. --no-cache]
#        then verify what is served: scripts/build_identity.py --expected <id>

set -euo pipefail
cd "$(dirname "$0")/.."

command -v git >/dev/null 2>&1 || {
  echo "build_app.sh: git is required to compute the build identity" >&2
  exit 1
}

BUILD_ID="$(git describe --always --dirty)"
[ -n "${BUILD_ID}" ] || { echo "build_app.sh: git produced no build identity" >&2; exit 1; }

SPAGO_BUILD_ID="${BUILD_ID}"
export SPAGO_BUILD_ID
echo "building app image with SPAGO_BUILD_ID=${BUILD_ID}"
docker compose build "$@" app
echo "verify what is served:  scripts/build_identity.py --expected ${BUILD_ID}"
