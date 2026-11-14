# Service availability runbook

How the API stays up, what took it down before, and what to do when it stops
answering. The incident record is at the bottom.

---

## Symptom

The site stops responding. SSH still works, the EC2 instance has been up for
months, and `systemctl restart` on the Harbour Hub units brings everything back.
Nothing in the application logs explains it, because the application was never
the thing that failed.

---

## What actually failed

**nginx failed to start and nothing restarted it.**

nginx resolves a hostname inside `proxy_pass` exactly once, at startup. If that
lookup fails, `nginx -t` fails, the unit start fails, and because Ubuntu ships
`Restart=no` for nginx, the unit stays dead until a human intervenes. The API is
then unreachable even though gunicorn, Celery, the database, and Redis are all
healthy.

The hostname was the S3 bucket:

```nginx
location /static/ {
    proxy_pass https://harbour-hub-storage.s3.eu-north-1.amazonaws.com/static/;
}
```

The trigger was a daily unattended upgrade. `needrestart` restarts services after
a `libc6` upgrade, which restarts nginx. During that window `systemd-resolved` is
also restarting, so `127.0.0.53` briefly refuses queries and the S3 lookup fails.
The failure is a race, which is why it hit on some mornings and not others.

### Evidence

Both outages are the same failure, seven days apart:

| Date | nginx stopped | nginx started | Downtime | Cause in log |
|---|---|---|---|---|
| 2026-11-04 | 06:02:26 | 11:02:05 | ~5 h | `host not found in upstream "harbour-hub-storage.s3.eu-north-1.amazonaws.com"` |
| 2026-11-13 | 06:19:14 | 2026-11-14 14:36 | ~32 h | same |

Both were preceded by `apt-daily-upgrade.service` and a `needrestart` restart.
The access log confirms the same gaps: no requests between 05:00 and 11:00 on
4 November, and none between 06:00 on 13 November and 14:00 on 14 November.

Two other upgrades on 23 and 27 October restarted nginx successfully, which is
what a race looks like: same trigger, different outcome.

---

## The fix, in three layers

Each layer alone would have prevented the long outage; together they also make
the next failure visible and short.

### 1. nginx no longer depends on startup DNS

`/etc/nginx/sites-available/harbourhub` resolves S3 per request:

```nginx
resolver 127.0.0.53 valid=30s ipv6=off;
resolver_timeout 5s;
set $s3_storage "harbour-hub-storage.s3.eu-north-1.amazonaws.com";

location /static/ {
    proxy_pass https://$s3_storage$request_uri;
    proxy_ssl_server_name on;
    proxy_set_header Host $s3_storage;
}
```

Putting the host in a variable moves resolution from config-load time to request
time. A DNS blip now costs a single failed `/static/` request instead of the
whole API. `proxy_ssl_server_name on` keeps SNI and certificate validation
working against the bucket.

Versioned copy: [`../../deploy/nginx/harbourhub.conf`](../../deploy/nginx/harbourhub.conf).

### 2. nginx restarts itself

`/etc/systemd/system/nginx.service.d/restart.conf` sets `Restart=always` with a
5-second delay and a ten-starts-in-five-minutes limit. A failed start is retried
instead of parking the unit in `failed`.

Versioned copy: [`../../deploy/systemd/nginx.service.d/restart.conf`](../../deploy/systemd/nginx.service.d/restart.conf).

### 3. A watchdog recovers anything else

`harbourhub-watchdog.timer` runs every two minutes. The script:

1. restarts nginx if the unit is inactive;
2. requests `https://api.harbourhubglobal.com/api/docs/` through nginx on
   `127.0.0.1`, retrying once after five seconds;
3. on a non-200, restarts `harbourhub-web` and `harbourhub-worker`, then retries;
4. still failing, restarts `nginx` and `harbourhub-beat`;
5. writes one line per recovery to `/var/log/harbourhub-watchdog.log`.

It is silent while healthy, so any line in that log is a recovery that happened.

The probe targets a documentation URL that does not query the database on
purpose. If the database is unreachable, restarting gunicorn does not help, and
a restart loop would only add noise on top of the real outage.

Versioned copies: [`../../deploy/bin/harbourhub-watchdog`](../../deploy/bin/harbourhub-watchdog),
[`../../deploy/systemd/harbourhub-watchdog.service`](../../deploy/systemd/harbourhub-watchdog.service),
[`../../deploy/systemd/harbourhub-watchdog.timer`](../../deploy/systemd/harbourhub-watchdog.timer).

---

## Verification performed (2026-11-14, production)

| Check | Result |
|---|---|
| `nginx -t` after the rewrite | passes |
| `/static/admin/css/base.css` | `200` |
| `/static/admin/js/nav_sidebar.js` | `200` |
| `/media/` | `403` (unchanged; the bucket denies listing) |
| `/api/docs/` | `200` |
| `kill -9` on the nginx master | restarted automatically after 5 s, API `200` |
| `systemctl stop harbourhub-web` | watchdog logged `health 502`, restarted web and worker, API `200`, unit active |
| `systemctl show nginx -p Restart` | `Restart=always`, `RestartUSec=5s` |
| `harbourhub-watchdog.timer` | active, next run within two minutes |

Not verified: a real unattended-upgrade run during a DNS outage. The change
removes the startup dependency rather than making DNS reliable, and the two
crash injections above cover the restart paths that previously stayed down.

---

## When the site stops again

Work down this list; each step narrows the layer.

```bash
# 1. Is the machine up and is it the app or the edge?
uptime
systemctl is-active nginx harbourhub-web harbourhub-worker harbourhub-beat

# 2. Did something recover already?
sudo tail -n 30 /var/log/harbourhub-watchdog.log
systemctl status harbourhub-watchdog.timer

# 3. Is nginx the problem?
sudo nginx -t
sudo journalctl -u nginx --since "1 hour ago" --no-pager | tail -n 40

# 4. Is the app the problem?
curl -s -o /dev/null -w "%{http_code}\n" https://api.harbourhubglobal.com/api/docs/
sudo tail -n 40 /var/www/harbourhub/logs/gunicorn-error.log
sudo journalctl -u harbourhub-web --since "1 hour ago" --no-pager | tail -n 40

# 5. Is a dependency the problem?
sudo ss -ltnp | grep -E "443|5432|6379"
```

Then, as the last resort:

```bash
sudo systemctl restart nginx harbourhub-web harbourhub-worker harbourhub-beat
```

### Reading the answers

| Observation | Meaning | Action |
|---|---|---|
| All units active, `/api/docs/` 200 | Already recovered | Read the watchdog log for when and why |
| nginx `failed`, `nginx -t` prints an `emerg` line | Config or DNS problem | Fix the config; do not blindly restart |
| nginx active, `/api/docs/` 502 | gunicorn down or socket missing | `systemctl restart harbourhub-web` |
| nginx active, `/api/docs/` 504 | gunicorn alive but slow | Check the database and Redis, then `proxy_read_timeout` |
| HTTP probe returns `000` | TLS handshake failed | Check certificate expiry with `sudo certbot certificates` |
| nginx restart-loops | Config is broken, not transient | `journalctl -u nginx`; the 10-in-5-minutes limit will pause it |

If nginx restarts continually, the cause is a bad config rather than a blip.
Automatic restarts cannot fix that, and the start limit stops the loop. That is
the case where a person is genuinely needed.

---

## Known limits

- **The watchdog does not monitor the database or Redis.** They are managed AWS
  services; restarting local units would not help, and the probe stays
  database-free so a database outage is not mistaken for an application crash.
- **The watchdog does not check certificate expiry.** An expired certificate
  produces `000` and a restart loop, because a restart cannot renew it. Certbot's
  own timer handles renewal; check `sudo certbot certificates` if you see `000`.
- **`needrestart` still restarts nginx during upgrades.** That is now harmless:
  nginx can start without DNS, and a failed start is retried.
- **A restarted service is not a fixed bug.** If the watchdog log shows repeated
  recoveries, read the unit journal for the reason instead of treating the
  restart as the fix.

---

## History

- **2026-11-04** — 5 hours down. First occurrence; recovered by a manual start.
- **2026-11-13 06:19 → 2026-11-14 14:36** — 32 hours down. nginx stopped by
  `needrestart`, failed to start on the S3 lookup, `Restart=no` left it down.
  Diagnosed from `journalctl -u nginx`, `apt-daily-upgrade` history, and the
  nginx access-log gap.
- **2026-11-14** — All three layers above installed and verified in production.
