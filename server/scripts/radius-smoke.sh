#!/usr/bin/env bash
set -euo pipefail
# Run only on an isolated CI runner, never on an existing RADIUS installation.
export FG_REST_ORIGIN=http://127.0.0.1:8080
export FG_NAS_KEY
FG_NAS_KEY=$(python - <<'PY'
import os
from datetime import datetime,timedelta,timezone
from fg_server.service import Service
s=Service(os.environ['FG_DATABASE_URL']);s.migrate()
s.provision_radius_user('radius-ci','main','packet-user','Packet password 123',datetime.now(timezone.utc)+timedelta(hours=1))
print(s.provision_nas('radius-ci','main','ci-nas'))
PY
)
# Mask the disposable CI key in packet diagnostics.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then echo "::add-mask::$FG_NAS_KEY"; fi
python -m fg_server serve >/tmp/fg-http.log 2>&1 &
api_pid=$!
radius_pid=''
trap 'kill "$api_pid" ${radius_pid:+"$radius_pid"} 2>/dev/null || true' EXIT
for attempt in $(seq 1 20); do curl -fsS http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
sudo systemctl stop freeradius || true
sudo cp radius/fg_mtm_rest.conf /etc/freeradius/3.0/mods-enabled/fg_mtm_rest
sudo cp radius/fg_mtm_site.conf /etc/freeradius/3.0/sites-enabled/fg_mtm_test
sudo env FG_REST_ORIGIN="$FG_REST_ORIGIN" FG_NAS_KEY="$FG_NAS_KEY" freeradius -XC >/tmp/fg-radius-config.log 2>&1 || { cat /tmp/fg-radius-config.log; exit 1; }
sudo env FG_REST_ORIGIN="$FG_REST_ORIGIN" FG_NAS_KEY="$FG_NAS_KEY" freeradius -X > /tmp/fg-radius.log 2>&1 &
radius_pid=$!
sleep 2
printf 'User-Name = "packet-user"\nUser-Password = "Packet password 123"\nMessage-Authenticator = 0x00\n' | radclient -x -r 1 -t 10 127.0.0.1:11812 auth testing123 > /tmp/fg-accept.log
grep -q 'Access-Accept' /tmp/fg-accept.log
printf 'User-Name = "packet-user"\nUser-Password = "wrong"\nMessage-Authenticator = 0x00\n' | radclient -x -r 1 -t 10 127.0.0.1:11812 auth testing123 > /tmp/fg-reject.log || true
grep -q 'Access-Reject' /tmp/fg-reject.log
for status in Start Interim-Update Stop Stop; do
    case "$status" in Start) seconds=0;; Interim-Update) seconds=30;; Stop) seconds=60;; esac
    printf 'User-Name = "packet-user"\nAcct-Session-Id = "packet-session"\nAcct-Status-Type = "%s"\nAcct-Session-Time = %s\nAcct-Input-Octets = %s\nAcct-Input-Gigawords = 1\nNAS-IP-Address = 127.0.0.1\n' "$status" "$seconds" "$seconds" | radclient -x -r 1 -t 10 127.0.0.1:11813 acct testing123 > /tmp/fg-accounting.log
    grep -q 'Accounting-Response' /tmp/fg-accounting.log
done
python - <<'PY'
import os
from fg_server.service import Service
s=Service(os.environ['FG_DATABASE_URL'])
while s.work():pass
with s.connect() as db:
    row=db.execute("SELECT * FROM radius_sessions WHERE tenant='radius-ci' AND username='packet-user'").fetchone()
    assert row and row['stopped'], 'Accounting packets did not create a stopped session'
    assert row['seconds']==60 and row['input_octets']==2**32+60
    count=db.execute("SELECT count(*) AS n FROM events WHERE tenant='radius-ci'").fetchone()['n']
    assert count==3, 'Duplicate Stop packet must not create another event'
print('PAP accept/reject and accounting Start/Interim/Stop/replay packet integration passed')
PY
