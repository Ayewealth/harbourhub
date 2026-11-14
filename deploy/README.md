# Server-side deployment artefacts

These files live outside the application directory on the production host, so
`git reset --hard` during a deploy does not manage them. This directory is the
versioned copy; installing or changing them is a manual step on the server.

Everything here is running in production as of `2026-11-14`. The reason each
file exists, and how to verify it, is in
[`../docs/ops/service-availability.md`](../docs/ops/service-availability.md).

| File | Installed as |
|---|---|
| `nginx/harbourhub.conf` | `/etc/nginx/sites-available/harbourhub` (symlinked from `sites-enabled`) |
| `systemd/nginx.service.d/restart.conf` | `/etc/systemd/system/nginx.service.d/restart.conf` |
| `bin/harbourhub-watchdog` | `/usr/local/bin/harbourhub-watchdog` (mode `755`) |
| `systemd/harbourhub-watchdog.service` | `/etc/systemd/system/harbourhub-watchdog.service` |
| `systemd/harbourhub-watchdog.timer` | `/etc/systemd/system/harbourhub-watchdog.timer` |

## Installing

```bash
sudo install -m 644 deploy/nginx/harbourhub.conf /etc/nginx/sites-available/harbourhub
sudo install -D -m 644 deploy/systemd/nginx.service.d/restart.conf \
    /etc/systemd/system/nginx.service.d/restart.conf
sudo install -m 755 deploy/bin/harbourhub-watchdog /usr/local/bin/harbourhub-watchdog
sudo install -m 644 deploy/systemd/harbourhub-watchdog.service \
    /etc/systemd/system/harbourhub-watchdog.service
sudo install -m 644 deploy/systemd/harbourhub-watchdog.timer \
    /etc/systemd/system/harbourhub-watchdog.timer

sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now harbourhub-watchdog.timer
sudo systemctl reload nginx
```

`nginx/harbourhub.conf` contains Certbot-managed lines. If the certificate
renewal hook has rewritten the live file, diff before overwriting, and keep the
per-request S3 resolver block.

## Checking

```bash
systemctl show nginx -p Restart -p RestartUSec      # Restart=always, 5s
systemctl is-active harbourhub-watchdog.timer       # active
systemctl list-timers harbourhub-watchdog.timer     # next run within 2 min
sudo tail -n 20 /var/log/harbourhub-watchdog.log    # only writes on a recovery
```

The watchdog log is silent while everything is healthy. A line in it means a
recovery happened, and the timestamp says when.
