# Pterodactyl Panel + Wings on Docker Desktop (WSL2) — Step‑by‑step

> This guide shows how to run **Pterodactyl Panel** and **Wings** using **Docker Desktop on Windows (WSL2 integration)**. It aims for a single-server, Docker Compose based setup suitable for testing, development, or light production. It includes persistence, common gotchas, and troubleshooting notes.

---

## Overview / what you'll end up with

* Pterodactyl **Panel** (web UI, Laravel app) running in Docker.
* **MariaDB** and **Redis** as support services in Docker.
* **Wings** (daemon) running in Docker — can be on the same machine as panel or separate.
* Volumes mapped to the host so data survives restarts.
* Optional reverse proxy (Traefik / Nginx) for TLS/letsencrypt.

This guide assumes you want to run everything under Docker Desktop (WSL2 backend) using an Ubuntu WSL distro for editing/commands.

---

## Quick checklist (prereqs)

1. Windows 10/11 with WSL2 enabled.
2. Docker Desktop installed and configured to use WSL2 integration.
3. A WSL distro (e.g. `Ubuntu-22.04`) where you will run `git` and `docker compose`.
4. `git`, `curl`, and an editor (VSCode recommended).
5. Optional: domain name (recommended if you want public access and TLS).

---

## Important notes & networking gotchas

* Docker Desktop provides `host.docker.internal` for containers to reach the Windows host. Use that if your container needs to access services on Windows/WSL host. Some networking modes and edge cases may behave unexpectedly under WSL2 integration — see troubleshooting.
* Host networking (`network_mode: host`) is not available / behaves differently on Docker Desktop (WSL2). Avoid relying on host networking.
* If you intend to expose Wings publicly, use a proper firewall and secure the API key.

---

## Prepare environment (WSL2)

Open your Ubuntu WSL shell and run:

```bash
# update + essential tools
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl unzip

# make a working dir
mkdir -p ~/pterodactyl-docker && cd ~/pterodactyl-docker
```

Make sure Docker CLI is available (installed by Docker Desktop). Test:

```bash
docker version
docker compose version
```

If those fail, open Docker Desktop and ensure WSL Integration is enabled for your distro (Settings → Resources → WSL Integration).

---

## Grab a Docker Compose setup

There are multiple community repositories that provide a nearly ready Docker Compose setup for Panel + Wings. Choose one you trust; this guide uses a straightforward single-server compose as a reference.

Example clone (pick one repo you prefer):

```bash
# Example: community single-server compose
git clone https://github.com/cskujawa/pterodactyl-single-server-docker-compose.git pterodactyl-docker
cd pterodactyl-docker
```

Alternatively you can use other maintained repos such as the `saibotk/pterodactyl-panel-docker` family or `YoshiWalsh/docker-pterodactyl-panel` — inspect their READMEs to see differences.

---

## Inspect the compose layout

Typical services you'll see in the compose tree:

* `panel` (php-fpm/apache or php-fpm/nginx + artisan tasks)
* `panel-worker` or `cron` (queue and scheduled jobs)
* `database` (mariadb)
* `redis`
* `wings` (daemon)
* optional: `nginx` / `traefik` reverse proxy

Open the repo and locate the `.env` example for the panel and for wings. Usually each service has its own `.env` file.

---

## Configure `.env` files

Copy examples and edit values.

```bash
# panel
cp panel/.env.example panel/.env
# wings (if present)
cp wings/.env.example wings/.env
```

Key fields to set in `panel/.env`:

* `APP_URL` → `http://localhost:8080` (or `https://panel.yourdomain.tld` if using a domain)
* `DB_HOST` → name of the database service from `docker-compose.yml` (often `database`)
* `DB_PASSWORD` → set a strong password
* `REDIS_HOST` → `redis`
* Mail settings (optional) — set SMTP if you want password resets to work

Key fields for `wings/.env`:

* `WINGS_PENDING_HOST` / `WINGS_HOST` → If the panel will contact Wings remotely, use the container host that the panel can reach. On single-server setups you can often use `wings` service name or `host.docker.internal` if needed.
* `WINGS_PORT` → default port (e.g., `8081`)
* `DATA_DIR` → where Wings stores server data (ensure this maps to a volume so game files persist)

---

## Volumes & persistence

Make sure the compose maps persistent volumes for:

* MariaDB data directory
* Redis data (optional)
* Panel storage (uploads)
* Wings `data` directory (game servers)

Example snippet (compose v2 style):

```yaml
services:
  database:
    image: mariadb:10.5
    volumes:
      - db_data:/var/lib/mysql

  wings:
    image: ghcr.io/pterodactyl/wings:latest
    volumes:
      - wings_data:/var/lib/pterodactyl

volumes:
  db_data:
  wings_data:
```

Using named volumes in Docker Desktop is fine; if you need the files directly on the WSL filesystem, use bind mounts to a folder under `~`.

---

## Start the stack

From the repo root:

```bash
docker compose up -d
```

Watch logs for errors:

```bash
docker compose logs -f
```

Check `docker ps` to confirm containers are healthy.

---

## Panel first-time setup (artisan commands)

Run the migrations and create keys / admin user (example commands; adjust service name if different):

```bash
# run migrations & generate key
docker compose exec panel php artisan key:generate
docker compose exec panel php artisan migrate --seed --force

docker compose exec panel php artisan p:user:make
# follow the interactive prompts to create an admin user
```

If your `panel` service uses a different workdir or user, you might need `docker compose exec panel bash` then run `php artisan ...` inside.

---

## Configure Wings and add Node in Panel

1. In Panel UI ([http://localhost:8080](http://localhost:8080)) log in as admin and go to **Nodes → New Node**.
2. Set the FQDN/IP and port of Wings (if Wings is in Docker Compose on same host, you can use `host.docker.internal:8081` or the mapped host port).
3. Generate a node token in the panel and copy it.
4. Configure `wings`'s `config.yml` or env to have that token so Wings can register with the Panel.

If Wings is running as a container, ensure the container exposes the port `8081` and that the compose maps it to the host (`ports:`). Example:

```yaml
wings:
  image: ghcr.io/pterodactyl/wings:latest
  ports:
    - "8081:8081"
  volumes:
    - ./wings/data:/var/lib/pterodactyl
```

Notes about using `host.docker.internal`:

* Docker Desktop provides this name for containers to reach the host; in many single-machine setups it is the easiest way for the panel container to reach Wings if Wings is bound to the host network or a different network.
* If you run both panel and wings in the same compose project and attach them to the same network, use the service name (e.g. `wings:8081`) instead of `host.docker.internal`.

---

## Reverse proxy & TLS (optional, recommended for public access)

If using a domain, put a reverse proxy in front of the Panel (and optionally Wings) with TLS. Popular choices:

* **Traefik** (works well with Docker labels and Let's Encrypt automation)
* **Nginx** (manual certs or Certbot)

High-level steps with Traefik:

1. Add Traefik service in compose, map ports 80/443, mount ACME storage.
2. Set labels on `panel` container for host rule and TLS.
3. Ensure DNS points to your host.

---

## Backups

* Backup MariaDB dumps regularly (cron job or separate backup container)
* Backup Wings `data` folder (where game files are stored)
* Export Panel `.env` securely (contains DB creds)

Example DB dump:

```bash
docker exec -i $(docker ps -qf "name=database") mysqldump -u root -p'$DB_PASSWORD' panel_database > panel_backup.sql
```

---

## Troubleshooting (common issues)

### Container can't reach host / `host.docker.internal` doesn't resolve

* Ensure Docker Desktop WSL integration is enabled. Try `ping host.docker.internal` from inside a container.
* If you run Docker engine inside WSL2 without Docker Desktop, `host.docker.internal` might not exist — add `extra_hosts` or use `host-gateway` feature.

### Wings won't register with Panel

* Check that the node's FQDN/IP and port used in Panel match what Wings exposes.
* Confirm token is copied correctly and Wings can reach Panel URL (APP_URL must be reachable from Wings).

### Permissions / storage errors

* Ensure mapped volumes use correct ownership (Wings expects to write to its `data` dir). You may need to `chown` files from within the container.

### Database migration failures

* Ensure DB user has correct privileges and connection details are right in `.env`.

---

## Security checklist

* Use strong DB and admin passwords.
* If exposing Wings, restrict access with firewall rules; only allow Panel or specified IPs.
* Use TLS for Panel (Traefik or Nginx + Certbot).
* Keep images up to date.

---

## Useful commands summary

```bash
# start
docker compose up -d

# view logs
docker compose logs -f panel

docker compose logs -f wings

# shell into panel
docker compose exec panel bash

# artisan tasks
docker compose exec panel php artisan migrate --force
```

---

## References & further reading

(Official docs and community Docker setups are great references for advanced config.)

* Pterodactyl official docs — getting started and panel/wings guides.
* Docker Desktop WSL2 integration docs.
* Community docker-compose templates (search GitHub for pterodactyl docker).

---

## Wrap-up

That’s the full flow: prepare WSL + Docker Desktop, choose a Docker Compose setup, configure `.env` files and volumes, `docker compose up`, run artisan for the panel, register Wings with the panel, and (optionally) put a reverse proxy in front.

If you want, I can:

* produce a minimal `docker-compose.yml` and `.env` tailored to single-server local usage (with copy-paste ready content), or
* adapt the tutorial to use Traefik for automatic TLS, or
* make a checklist of commands you can copy into a script.

Tell me which one you want and I'll add it to the doc.
