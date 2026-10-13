#!/usr/bin/env bash
# Run from a reviewed extracted server bundle. No remote shell pipe, no data deletion.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Install Docker Engine and the Compose plugin first.' >&2; exit 1; }
docker compose version >/dev/null
if [[ -e .env ]]; then
  echo 'Existing .env detected. Keep it and back up PostgreSQL before an upgrade. Use the documented upgrade commands.' >&2
  exit 1
fi
[[ $# == 4 ]] || { echo 'Usage: bash scripts/start-ubuntu.sh DOMAIN TENANT_ID BRANCH_ID OWNER_USERNAME' >&2; exit 1; }
domain=$1; tenant=$2; branch=$3; username=$4
[[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ && "$domain" == *.* && "$domain" != *..* ]] || { echo 'Use a DNS hostname, without scheme, port or path.' >&2; exit 1; }
for value in "$tenant" "$branch" "$username"; do
  [[ "$value" =~ ^[A-Za-z0-9._:-]{1,120}$ ]] || { echo 'Invalid identifier.' >&2; exit 1; }
done
# Do not write config until Docker is reachable and the user-selected public ports are free.
docker info >/dev/null
if command -v ss >/dev/null && ss -H -ltn '( sport = :80 or sport = :443 or sport = :8080 )' | grep -q .; then
  echo 'Ports 80/443/8080 are in use. Use your existing reverse proxy or choose a separate host; no services were stopped.' >&2; exit 1
fi
umask 077
secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
printf 'FG_DB_PASSWORD=%s\nFG_DOMAIN=%s\n' "$secret" "$domain" > .env
unset secret
docker compose -p fg-mtm -f compose.yml -f compose.https.yml config --quiet
docker compose -p fg-mtm -f compose.yml -f compose.https.yml up -d --build
docker compose -p fg-mtm -f compose.yml -f compose.https.yml run --rm api python -m fg_server account --tenant "$tenant" --branch "$branch" --username "$username" --role owner
echo "Panel: https://$domain/panel/"
echo "Android server origin: https://$domain"
echo 'Verify DNS/TLS and sign in before connecting live devices. Keep .env and database backups private.'
