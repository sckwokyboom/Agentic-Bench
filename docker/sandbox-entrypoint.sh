#!/bin/sh
# Install Graph-Tipper's OpenCode tools from the mounted GT into the container's
# global OpenCode tools dir, so the model can use them (gating is decided per
# run via the workdir opencode.json). No-op when GT is not mounted.
#
# Paths are overridable via GT_TOOLS / DEST (defaults are the production
# container paths) so the logic can be tested without building the image.
set -eu
GT_TOOLS="${GT_TOOLS:-/opt/graph-tipper/integrations/opencode/tools}"
DEST="${DEST:-/root/.config/opencode/tools}"
if [ -d "$GT_TOOLS" ]; then
    mkdir -p "$DEST"
    n=0
    for f in "$GT_TOOLS"/*.ts; do
        [ -e "$f" ] || continue
        cp "$f" "$DEST/"; n=$((n + 1))
    done
    echo "[sandbox-entrypoint] installed $n GT OpenCode tool(s) into $DEST" >&2
fi

# The run workdir is bind-mounted from the host (owned by the host uid), so the
# container's root user trips git's "dubious ownership" guard. That would make
# BOTH the agent's git and the `impact` tool's `git diff HEAD` fail (impact would
# silently see no changes). Trust any workdir so git just works.
git config --global --add safe.directory '*' 2>/dev/null || true

exec "$@"
