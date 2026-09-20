#!/usr/bin/env bash
# One-time setup for a fresh clone. Safe to re-run.
#
#   ./setup.sh          install deps, create .env, build the index
#   npm --prefix acme-chat run start
#
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
die() { printf '\n\033[1;31mx %s\033[0m\n' "$1" >&2; exit 1; }

command -v poetry >/dev/null || die "poetry not found. Install it: https://python-poetry.org/docs/#installation"
command -v npm    >/dev/null || die "npm not found. Install Node 18+ from https://nodejs.org"

say "Python dependencies"
poetry install

say "Frontend dependencies"
npm --prefix acme-chat install

say "Configuration"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "   created .env from .env.example"
else
  echo "   .env already exists, leaving it alone"
fi

if ! grep -qE '^OPENAI_API_KEY=sk-[A-Za-z0-9_-]+' .env; then
  echo
  echo "   !! .env has no OPENAI_API_KEY yet."
  echo "      Open .env and set OPENAI_API_KEY=sk-... before asking any questions."
  echo "      (Everything except 'ask' works without one.)"
fi

say "Corpus"
CORPUS="${ACME_CORPUS_DIR:-corpus/acme}"
if [ -d "$CORPUS" ] && [ -n "$(find "$CORPUS" -name '*.txt' -print -quit 2>/dev/null)" ]; then
  echo "   found $(find "$CORPUS" -name '*.txt' | wc -l | tr -d ' ') documents in $CORPUS"
else
  die "no corpus at '$CORPUS'.
      Copy the archive so that it lands at:   $(pwd)/corpus/acme/
      It should contain transcripts/, emails/ and reports/.
      Or point ACME_CORPUS_DIR in .env at wherever you keep it."
fi

say "Building the index"
poetry run acme-agent build

say "Done"
cat <<'EOF'

Start everything with:

    npm --prefix acme-chat run start

Then open http://localhost:5173

  api  -> FastAPI on :8000   (the agent, the index, erasure)
  web  -> Vite on :5173      (the three role views; proxies /api to :8000)

EOF
