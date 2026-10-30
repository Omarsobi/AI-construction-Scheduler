#!/usr/bin/env bash
# Sets up Harvey (github.com/ethanplusai/harvey, MIT) for Omar's construction outreach.
# Idempotent. Run from anywhere: bash outreach/setup.sh
# Windows: run the same steps by hand with .venv\Scripts\activate instead of source.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HARVEY="$HERE/harvey"
PIN=4237f07f5873e270c362b43aec76e60fc4faa9cf   # upstream commit the patch was written against

[ -d "$HARVEY/.git" ] || git clone https://github.com/ethanplusai/harvey "$HARVEY"
git -C "$HARVEY" fetch -q origin "$PIN" 2>/dev/null || git -C "$HARVEY" fetch -q --unshallow origin
git -C "$HARVEY" checkout -q "$PIN"

# One follow-up maximum: 2-email sequences instead of Harvey's 3. Skip if already applied.
git -C "$HARVEY" apply --check "$HERE/patches/two-email-sequence.patch" 2>/dev/null \
  && git -C "$HARVEY" apply "$HERE/patches/two-email-sequence.patch"

# Omar's config and product file live in this repo; Harvey reads them via symlink.
ln -sfn "$HERE/harvey.local.yaml" "$HARVEY/harvey.local.yaml"
ln -sfn "$HERE/skills/product_knowledge.md" "$HARVEY/skills/product_knowledge.md"

[ -d "$HARVEY/.venv" ] || python3 -m venv "$HARVEY/.venv"
"$HARVEY/.venv/bin/pip" install -q -e "$HARVEY[dev]"

cd "$HARVEY"
.venv/bin/harvey status --check
echo "Done. Next: cd outreach/harvey && source .venv/bin/activate && harvey signals --confirm free"
