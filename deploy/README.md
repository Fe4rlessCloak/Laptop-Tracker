# Deploying the OLX Scraper to the Ubuntu mini PC

This guide walks you through one-time setup of the OLX Pakistan laptop scraper
on the Ubuntu mini PC, plus the day-to-day operations (verify, rollback, log
inspection).

The deployment is **three layers**:

1. **Container image** — published to `ghcr.io/fe4rlesscloak/laptop-tracker` by
   the GitHub Actions `Release` workflow (see `.github/workflows/release.yml`).
   You do not need to build the image on the box.
2. **systemd timer** — fires `olx-scraper.service` twice a day (09:00 and 21:00
   local). The service runs `docker run` against the image, writes its SQLite
   DB + CSV/JSON exports to a named volume, and exits.
3. **Named Docker volume** — `laptop-tracker-data` holds the database and
   exports on the host, surviving container restarts.

---

## One-time setup (run once per Ubuntu box)

You will need SSH access to the box and `sudo` privileges.

### 1. Install Docker (skip if already installed)

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# log out and back in so the docker group takes effect
```

Verify:

```bash
docker --version
docker compose version
```

### 2. Log in to ghcr.io (one-time)

The image at `ghcr.io/fe4rlesscloak/laptop-tracker` is private. You need a
GitHub Personal Access Token (PAT) with `read:packages` scope to pull it.

1. Create a PAT at <https://github.com/settings/tokens?type=beta> with
   `read:packages` (Fine-grained token, Resource owner = your user).
2. On the box, log in:

   ```bash
   sudo docker login ghcr.io
   # Username: <your github username>
   # Password: <paste the PAT>
   ```

   The credentials are persisted in `/root/.docker/config.json` and reused
   on every subsequent `docker pull`.

### 3. Pre-create the named volume

```bash
sudo docker volume create laptop-tracker-data
```

This is technically optional (the systemd service creates the volume on first
run), but pre-creating it makes the data path discoverable via
`docker volume inspect laptop-tracker-data` before any scrape has run.

### 4. Copy the systemd unit files

From your laptop, after the Implementation session has committed them:

```bash
# from the project root on your laptop
scp deploy/systemd/olx-scraper.service deploy/systemd/olx-scraper.timer \
    <user>@<box>:~/

# on the box
sudo mv ~/olx-scraper.service ~/olx-scraper.timer /etc/systemd/system/
sudo chown root:root /etc/systemd/system/olx-scraper.service /etc/systemd/system/olx-scraper.timer
sudo chmod 644 /etc/systemd/system/olx-scraper.service /etc/systemd/system/olx-scraper.timer
```

### 5. Enable and start the timer

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now olx-scraper.timer
```

`enable --now` does two things: registers the timer to start at boot, and
starts it right now.

### 6. Verify

```bash
# When does the next scrape run?
systemctl list-timers olx-scraper.timer

# Pull and run the scrape manually right now (useful for a sanity check)
sudo systemctl start olx-scraper.service

# Watch the live logs of the current run
sudo journalctl -u olx-scraper.service -f

# Inspect the named volume — where the data lives on the host
sudo docker volume inspect laptop-tracker-data
```

The scraper writes the SQLite DB and dated exports to the volume mounted at
`/app/data` inside the container. The host path is whatever
`docker volume inspect laptop-tracker-data` shows under `Mountpoint` (typically
`/var/lib/docker/volumes/laptop-tracker-data/_data`).

---

## Day-to-day operations

### "Is the scraper working?"

```bash
# Last 100 lines of the most recent run
sudo journalctl -u olx-scraper.service -n 100

# Did the last run complete without errors?
sudo systemctl status olx-scraper.service
```

A successful run ends with a line like
`Fetched 109 listings, 75 new, 34 updated, 0 skipped, 0 errors` and the
process exit code 0.

### "What data is in the DB?"

```bash
# Inspect the SQLite database from the host
sudo docker run --rm \
    -v laptop-tracker-data:/data \
    --entrypoint sqlite3 \
    ghcr.io/fe4rlesscloak/laptop-tracker:latest \
    /data/olx.db "SELECT COUNT(*), MIN(scraped_at), MAX(scraped_at) FROM listings;"
```

(Side note: the official Python image has no `sqlite3` CLI binary; the
`--entrypoint sqlite3` override is illustrative. If you need direct DB
access, install `sqlite3` on the host with `sudo apt install sqlite3` and
point it at the volume's mountpoint instead.)

### "I want to release a new version"

1. Merge your changes to `main` (or push a `v*` tag for a numbered release).
2. The GitHub Actions `Release` workflow runs. Watch it at
   <https://github.com/Fe4rlessCloak/Laptop-Tracker/actions>.
3. On green, the new image is at `ghcr.io/fe4rlesscloak/laptop-tracker:latest`.
4. The next scheduled scrape on the box pulls it automatically (because
   `olx-scraper.service` uses `--pull=always`).
5. If you want the new version *right now* without waiting for the timer:
   `sudo systemctl start olx-scraper.service`.

### "Rollback to a previous version"

The `--pull=always` flag in `olx-scraper.service` always pulls the latest
image, which is `:latest` by default. To pin to a specific version:

1. List the available tags at
   <https://github.com/Fe4rlessCloak/Laptop-Tracker/pkgs/container/laptop-tracker>.
   Tags include:
   - `latest` (rolling, every push to main)
   - `sha-<short-sha>` (immutable, one per build)
   - `v1.0.0`, `v1.0.1`, ... (semantic versions, only on `v*` tags)
2. Edit the systemd service:
   ```bash
   sudo systemctl edit olx-scraper.service
   ```
   This opens an override file. Add:
   ```ini
   [Service]
   ExecStart=
   ExecStart=/usr/bin/docker run --rm --pull=always \
       -v laptop-tracker-data:/app/data \
       ghcr.io/fe4rlesscloak/laptop-tracker:v1.0.0 \
       --hours 24 --export csv json
   ```
   The empty `ExecStart=` clears the original; the next line replaces it.
3. Reload and verify:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start olx-scraper.service
   sudo journalctl -u olx-scraper.service -n 50
   ```
4. To return to rolling `:latest`, just `sudo systemctl revert olx-scraper.service`
   and `sudo systemctl daemon-reload`.

### "Where is the data on disk?"

```bash
sudo docker volume inspect laptop-tracker-data --format '{{ .Mountpoint }}'
# Typical answer: /var/lib/docker/volumes/laptop-tracker-data/_data
sudo ls -la /var/lib/docker/volumes/laptop-tracker-data/_data
# Expect to see: olx.db, listings-2026-08-30.csv, listings-2026-08-30.json, ...
```

### "I want to nuke the data and start fresh"

```bash
sudo systemctl stop olx-scraper.timer  # stop scheduling
sudo docker volume rm laptop-tracker-data
sudo docker volume create laptop-tracker-data
sudo systemctl start olx-scraper.timer  # resume scheduling
```

This is destructive — `olx.db` and all dated exports are gone. Confirm you
have copies elsewhere first.

---

## Troubleshooting

### "The scrape keeps failing with 'fetch failed'"

Check your box's outbound network and DNS:

```bash
curl -I https://www.olx.com.pk/
```

OLX occasionally rate-limits or returns 5xx. The scraper has retry/backoff
(see `MAX_RETRIES` and `RETRY_BACKOFF` in `scraper/config.py`); a transient
failure usually clears on the next scheduled run.

### "The systemd timer isn't firing"

```bash
systemctl list-timers olx-scraper.timer
sudo journalctl -u olx-scraper.timer -n 50
```

Common causes:
- The timer's clock is wrong (`timedatectl`).
- `olx-scraper.service` exited with a non-zero status and systemd disabled
  the timer. Re-enable with `sudo systemctl reset-failed olx-scraper.service`.

### "I see logs but no data in the DB"

The container ran but the volume is missing or empty. Check:

```bash
sudo docker volume ls | grep laptop-tracker
sudo docker run --rm -v laptop-tracker-data:/data alpine ls -la /data
```

If the volume exists but `/data` is empty, the container exited before
writing — check `journalctl` for the error.
