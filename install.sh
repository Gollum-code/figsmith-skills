#!/usr/bin/env bash
# FigSmith installer - full or single-domain.
#
#   ./install.sh                          # full install (all domains)
#   ./install.sh --core-only              # core + verify only
#   ./install.sh --domain paper-figure     # core + one domain
#   ./install.sh --target ~/.claude/skills  # install into a specific host dir
#
# The skill tree is plain files; "installing" means copying the tree into a location
# the host agent scans for SKILL.md. Nothing is compiled, nothing is registered.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${HOME}/.claude/skills"
MODE="full"
DOMAIN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --core-only) MODE="core"; shift ;;
    --domain) MODE="domain"; DOMAIN="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" == "domain" && -z "$DOMAIN" ]]; then
  echo "--domain requires a domain name" >&2
  exit 2
fi

if [[ "$MODE" == "domain" && ! -d "$REPO_ROOT/domains/$DOMAIN" ]]; then
  echo "no such domain: $DOMAIN" >&2
  echo "available: $(ls "$REPO_ROOT/domains")" >&2
  exit 2
fi

DEST="$TARGET/figsmith"
mkdir -p "$DEST"

copy_tree() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  cp -R "$src/." "$dst/"
}

copy_file() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp -f "$src" "$dst"
}

echo "installing figsmith ($MODE${DOMAIN:+ $DOMAIN}) -> $DEST"

# core is always installed: tokens, IR, verify, backends
copy_tree "$REPO_ROOT/core" "$DEST/core"
copy_tree "$REPO_ROOT/backends" "$DEST/backends"
# A single file is copied as a file. Routing it through copy_tree created a *directory*
# named README.md and then `cp -R README.md/.` failed with ENOTDIR, which aborted the
# install under `set -e` - on the README's own quick-start command.
copy_file "$REPO_ROOT/README.md" "$DEST/README.md"
# The verification commands in AGENTS.md section 4 run against the installed tree, so
# the tree needs the modules they invoke.
copy_tree "$REPO_ROOT/tools" "$DEST/tools"
copy_tree "$REPO_ROOT/tests" "$DEST/tests"
copy_file "$REPO_ROOT/requirements.txt" "$DEST/requirements.txt"
copy_file "$REPO_ROOT/AGENTS.md" "$DEST/AGENTS.md"
copy_tree "$REPO_ROOT/docs" "$DEST/docs"
# The router is part of tools/ and is installed in every mode, so it needs the merged
# catalog to answer from. Shipping only the index (not the whole gallery/) keeps a
# core-only install minimal while still making `python -m tools.catalog route` work.
if [[ -f "$REPO_ROOT/gallery/catalog.json" ]]; then
  mkdir -p "$DEST/gallery"
  copy_file "$REPO_ROOT/gallery/catalog.json" "$DEST/gallery/catalog.json"
fi

if [[ "$MODE" == "full" ]]; then
  copy_tree "$REPO_ROOT/domains" "$DEST/domains"
  copy_tree "$REPO_ROOT/examples" "$DEST/examples"
  copy_tree "$REPO_ROOT/gallery" "$DEST/gallery"
elif [[ "$MODE" == "domain" ]]; then
  mkdir -p "$DEST/domains"
  copy_tree "$REPO_ROOT/domains/$DOMAIN" "$DEST/domains/$DOMAIN"
  if [[ -d "$REPO_ROOT/examples/$DOMAIN" ]]; then
    copy_tree "$REPO_ROOT/examples/$DOMAIN" "$DEST/examples/$DOMAIN"
  fi
fi

cat <<EOF

done. what got installed:
  core/       METHOD.md, IR.md, tokens/, probe/, verify/
  backends/   svg, png, mpl2svg, pdf, drawio, pptx, html2pdf
  tools/      router, regression, gallery, four-way, pipeline
  tests/      fixtures, blessed baselines, unit tests
  docs/       cookbook, spike notes, vision probe report
$(if [[ "$MODE" == "full" ]]; then
  echo "  domains/    all 7 domain packages"
  echo "  examples/   regenerable cases"
  echo "  gallery/    offline chart-type gallery"
elif [[ "$MODE" == "domain" ]]; then
  echo "  domains/    $DOMAIN"
  echo "  examples/   $DOMAIN cases (if any)"
fi)

verify the install:
  cd "$DEST" && python tools/regress.py && python tests/test_verify.py

the agent finds this by SKILL.md. see AGENTS.md for host-specific notes.
EOF
