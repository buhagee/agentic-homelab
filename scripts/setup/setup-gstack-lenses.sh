#!/usr/bin/env bash
# Reproduce the pinned, curated gstack OpenCode install.
#
# This writes to the persistent OpenCode home; it does not touch the tracked
# config. Run it once on a new host, then `deploy` the tracked config.
set -euo pipefail

GSTACK_VERSION="1.99.5.0"
BUN_VERSION="1.4.2"
BUN_SHA256="36368faef7527875d5ffa52e53cd48021741f2a83eb6208a8dd64068d422a913"

GSTACK_HOME="${HOME}/.local/share/gstack"
GSTACK_SRC="${GSTACK_HOME}/src"
INSTALL_HOME="${GSTACK_HOME}/home"
INSTALL_SKILLS="${INSTALL_HOME}/.config/opencode/skills"
STATE_ROOT="${HOME}/.gstack"
BUN_BIN="${HOME}/.local/bin/bun"

ALLOWED="office-hours plan-ceo-review plan-eng-review review qa-only cso document-release verify test-audit careful freeze unfreeze health"

info() { printf '[gstack] %s\n' "$*"; }
die()  { printf '[gstack] ERROR: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "git is required"
command -v python3 >/dev/null || die "python3 is required"
command -v sha256sum >/dev/null || die "sha256sum is required"

# Bun is required by gstack setup and by several skill runtimes. Keep it in the
# persistent home so the container PATH already includes it.
if [[ ! -x "$BUN_BIN" ]] || [[ "$("$BUN_BIN" --version 2>/dev/null || true)" != "$BUN_VERSION" ]]; then
  info "installing Bun ${BUN_VERSION} to ${BUN_BIN}"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/bun.zip" \
    "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-x64.zip"
  curl -fsSL -o "$tmp/SHASUMS256.txt" \
    "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/SHASUMS256.txt"
  echo "${BUN_SHA256}  ${tmp}/bun.zip" | sha256sum -c -
  python3 -m zipfile -e "$tmp/bun.zip" "$tmp"
  install -m 0755 "$tmp/bun-linux-x64/bun" "$BUN_BIN"
fi
"$BUN_BIN" --version | grep -qx "$BUN_VERSION" || die "unexpected Bun version"

if [[ ! -d "$GSTACK_SRC/.git" ]]; then
  [[ -e "$GSTACK_SRC" ]] && die "${GSTACK_SRC} exists but is not a git checkout"
  info "cloning gstack v${GSTACK_VERSION}"
  git clone --quiet --depth 1 --branch "v${GSTACK_VERSION}" \
    https://github.com/garrytan/gstack.git "$GSTACK_SRC"
else
  info "reusing ${GSTACK_SRC}"
fi

mkdir -p "$INSTALL_HOME/.config/opencode" "$STATE_ROOT"

run_setup() {
  (
    cd "$GSTACK_SRC"
    PATH="${HOME}/.local/bin:${PATH}" \
      HOME="$INSTALL_HOME" \
      GSTACK_STATE_ROOT="$STATE_ROOT" \
      GSTACK_SKIP_PLAYWRIGHT=1 \
      ./setup --host opencode --prefix --no-browser --global
  )
}

# First pass generates the OpenCode skill tree. Then curate by name and re-run
# so disabled skills are not linked into the installed tree.
info "generating the OpenCode skills"
run_setup >/dev/null

all="$(find "$GSTACK_SRC/.opencode/skills" -mindepth 1 -maxdepth 1 -type d \
  -printf '%f\n' | sed 's/^gstack-//' | grep -v '^gstack$' | grep -v '^upgrade$' | sort)"
disabled="$(comm -23 <(printf '%s\n' $all) \
  <(printf '%s\n' $ALLOWED | tr ' ' '\n' | sort) | paste -sd, -)"

info "disabling non-allowed lenses"
PATH="${HOME}/.local/bin:${PATH}" \
  GSTACK_STATE_ROOT="$STATE_ROOT" \
  "$GSTACK_SRC/bin/gstack-config" set telemetry off >/dev/null
PATH="${HOME}/.local/bin:${PATH}" \
  GSTACK_STATE_ROOT="$STATE_ROOT" \
  "$GSTACK_SRC/bin/gstack-config" set update_check false >/dev/null
PATH="${HOME}/.local/bin:${PATH}" \
  GSTACK_STATE_ROOT="$STATE_ROOT" \
  "$GSTACK_SRC/bin/gstack-config" set codex_reviews disabled >/dev/null
PATH="${HOME}/.local/bin:${PATH}" \
  GSTACK_STATE_ROOT="$STATE_ROOT" \
  "$GSTACK_SRC/bin/gstack-config" set disabled_skills "$disabled" >/dev/null || true

info "installing the curated lens set"
run_setup >/dev/null

# Upgrade is special-cased by gstack and cannot be disabled through
# disabled_skills. Remove its advertised entry; the runtime remains available
# only through the forbidden list in the tracked config.
rm -f "$INSTALL_SKILLS/gstack-upgrade"

# qa-only references QA's browser section. Browser automation is intentionally
# absent, so keep the section next to qa-only and point the prose there. This is
# the same hand patch recorded in OpenMacrocycle's gstack policy.
qa_src="$GSTACK_SRC/.opencode/skills/gstack-qa-only"
mkdir -p "$qa_src/sections"
cp "$GSTACK_SRC/.opencode/skills/gstack-qa/sections/browser-setup.md" \
  "$qa_src/sections/browser-setup.md"
python3 - "$qa_src/SKILL.md" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text()
old = "Read `sections/browser-setup.md` relative to the installed `gstack-qa` SKILL.md directory in full."
new = "Read `sections/browser-setup.md` relative to this SKILL.md directory in full."
if old in text:
    p.write_text(text.replace(old, new))
PY

# The generated preambles fall back to ~/.config/opencode/skills/gstack.
# Point them at this persistent user-level install so they work without the
# compose environment (and remain correct after a container recreate).
python3 - "$GSTACK_SRC/.opencode/skills" "$INSTALL_SKILLS" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
installed = Path(sys.argv[2])
old = "~/.config/opencode/skills/gstack"
new = str(installed / "gstack")
for path in list(root.glob("gstack*/SKILL.md")) + list(root.glob("gstack*/sections/*.md")):
    text = path.read_text()
    if old in text:
        path.write_text(text.replace(old, new))
PY

# Drop registry rows whose install root no longer exists.
if [[ -f "$STATE_ROOT/installs.tsv" ]]; then
  python3 - "$STATE_ROOT/installs.tsv" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
rows = p.read_text().splitlines()
keep = [row for row in rows if row.startswith("#") or not row.strip() or Path(row.split("\t")[3]).exists()]
p.write_text("\n".join(keep) + ("\n" if keep else ""))
PY
fi

PATH="${HOME}/.local/bin:${PATH}" \
  HOME="$INSTALL_HOME" \
  GSTACK_STATE_ROOT="$STATE_ROOT" \
  GSTACK_SKIP_PLAYWRIGHT=1 \
  "$GSTACK_SRC/setup" --status

info "installed ${GSTACK_VERSION}; skills: ${INSTALL_SKILLS}"
