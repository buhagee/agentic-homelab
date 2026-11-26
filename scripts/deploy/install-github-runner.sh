#!/usr/bin/env bash
# Install a pinned GitHub Actions runner for the homeserver-deploy repository.
set -euo pipefail

RUNNER_VERSION="2.338.2"
RUNNER_SHA256="baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40"
RUNNER_USER="github-runner"
RUNNER_HOME="/home/github-runner"
RUNNER_DIR="${RUNNER_HOME}/actions-runner"
URL=""
TOKEN=""
NAME="$(hostname -s)"

usage() {
  echo "Usage: $0 --url <repository-url> --token <registration-token> [--name <runner-name>]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ -n "$URL" && -n "$TOKEN" ]] || usage
[[ "$(uname -m)" == "x86_64" ]] || { echo "This installer supports x86_64 only" >&2; exit 1; }

for command in curl tar sha256sum useradd runuser systemctl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Missing command: $command" >&2
    exit 1
  }
done

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir "$RUNNER_HOME" --shell /bin/bash \
    --comment "GitHub Actions runner" "$RUNNER_USER"
fi

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0755 "$RUNNER_DIR"

TARBALL="${RUNNER_DIR}/runner.tar.gz"
URL_TARBALL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

curl -fsSL -o "$TARBALL" "$URL_TARBALL"
echo "${RUNNER_SHA256}  ${TARBALL}" | sha256sum -c -
runuser -u "$RUNNER_USER" -- tar xzf "$TARBALL" -C "$RUNNER_DIR"
rm -f "$TARBALL"

runuser -u "$RUNNER_USER" -- "${RUNNER_DIR}/config.sh" \
  --unattended \
  --url "$URL" \
  --token "$TOKEN" \
  --name "$NAME" \
  --labels "homeserver-deploy" \
  --work "${RUNNER_DIR}/_work" \
  --replace

cd "$RUNNER_DIR"
./svc.sh install "$RUNNER_USER"
./svc.sh start

echo "Runner installed as ${NAME}"
echo "Check: systemctl status 'actions.runner.*' --no-pager"
