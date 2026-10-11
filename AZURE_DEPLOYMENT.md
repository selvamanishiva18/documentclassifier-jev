# Deploy on an Azure VM

The app runs on a single Ubuntu VM with the existing `docker-compose.yml`, and Caddy in front adds HTTPS. A single VM matches the PRD's single-replica, in-memory design, so no code changes are needed.

**You need:** an Azure subscription, the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login` done), and your `TYPESAFE_API_KEY`. `ANTHROPIC_API_KEY` is optional; set it to enable Precise mode.

---

### 1. Create the VM (2 vCPU / 4 GB, Ubuntu 24.04)

Run this on your machine. Change `docclassify-demo` to a unique name: it becomes your web address.

```bash
az group create --name docclassify-rg --location eastus
az vm create --resource-group docclassify-rg --name docclassify-vm \
  --image Ubuntu2404 --size Standard_B2s \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --public-ip-address-dns-name docclassify-demo
```

Your site will be `https://docclassify-demo.eastus.cloudapp.azure.com`.

### 2. Open web ports (80 and 443 only)

```bash
az vm open-port --resource-group docclassify-rg --name docclassify-vm --port 80,443
```

Ports 8000 and 5173 stay closed to the internet; only Caddy is public.

### 3. Connect to the VM

```bash
ssh azureuser@docclassify-demo.eastus.cloudapp.azure.com
```

All remaining steps run **on the VM**.

### 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

### 5. Get the code

Clone the repo:

```bash
git clone https://github.com/<your-org>/<your-repo>.git docclassify && cd docclassify
```

No repo? Copy the code from your machine instead. Run this on **your machine**, from the folder containing the project:

```bash
scp -r DocumentExtractor azureuser@docclassify-demo.eastus.cloudapp.azure.com:~/docclassify
```

Then `cd ~/docclassify` on the VM.

### 6. Add your keys

```bash
cp .env.example .env
nano .env          # set TYPESAFE_API_KEY=... (and ANTHROPIC_API_KEY=... for Precise mode)
chmod 600 .env
```

### 7. Start the app

```bash
docker compose up -d --build
curl -s http://localhost:8000/api/health
```

The health check should return `"status":"ok"` and `"tesseract":true`. Containers restart automatically after a reboot (`restart: unless-stopped`).

### 8. Turn on HTTPS with Caddy

#### What Caddy does here

Caddy is the only public entry point on the VM. It:

- **Gets and renews a free HTTPS certificate** from Let's Encrypt automatically. No certbot or cron job is needed.
- **Redirects `http://` to `https://`.**
- **Routes requests:** `/api/*` goes straight to the backend container, and everything else goes to the frontend container.
- **Sends the visitor's real IP** to the backend in the `X-Real-IP` header. The backend's limit of 30 uploads per hour per IP depends on this; without it, every visitor would look like the same IP.
- **Allows uploads up to 220 MB** (20 files × 10 MB plus overhead), the PRD limit.

#### Process flow

```
                       Azure VM (only ports 80/443 open in the NSG)
 ┌──────────┐  HTTPS  ┌──────────────────────────────────────────────────────────┐
 │ Browser  │────────►│  Caddy (systemd service, ports 80 → redirect, 443 TLS)   │
 └──────────┘         │     │                                                    │
                      │     ├── /api/*  ──► localhost:8000 ─► backend container  │
                      │     │                (FastAPI · Tesseract · Jev/Haiku)   │
                      │     │                                                    │
                      │     └── /*      ──► localhost:5173 ─► frontend container │
                      │                      (nginx serving the React app)       │
                      └──────────────────────────────────────────────────────────┘

First start: Caddy ──► Let's Encrypt (HTTP check on port 80) ──► certificate stored in /var/lib/caddy
Every ~60 days: Caddy renews the certificate in the background
```

#### 8.1 Install Caddy from its official repository

Ubuntu's own `caddy` package is often outdated; Caddy's repository gives the current stable release.

```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
caddy version
```

Installing the package also creates and starts a `caddy` systemd service, which serves a placeholder page on port 80.

#### 8.2 Write the Caddyfile

Replace the domain on the first line with yours from step 1:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
docclassify-demo.eastus.cloudapp.azure.com {
    # Match the PRD upload limit (20 files x 10 MB + multipart overhead)
    request_body {
        max_size 220MB
    }

    encode zstd gzip

    # API: straight to the backend, passing the visitor's real IP for rate limiting
    handle /api/* {
        reverse_proxy localhost:8000 {
            header_up X-Real-IP {remote_host}
        }
    }

    # Everything else: the React app
    handle {
        reverse_proxy localhost:5173
    }
}
EOF
```

#### 8.3 Check the config

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

`fmt` tidies the indentation. `validate` should end with `Valid configuration`.

#### 8.4 Apply it and start on boot

```bash
sudo systemctl enable caddy
sudo systemctl reload caddy
systemctl status caddy --no-pager
```

`reload` applies the new config without dropping connections. The status should show `active (running)`.

#### 8.5 Watch the certificate being issued

```bash
sudo journalctl -u caddy -f
```

Within about a minute, look for `certificate obtained successfully`. Press `Ctrl+C` to stop watching.

#### 8.6 Verify HTTPS and routing

```bash
DOMAIN=docclassify-demo.eastus.cloudapp.azure.com
curl -sI http://$DOMAIN | head -n 3              # expect 308 redirect to https://
curl -s https://$DOMAIN/api/health               # expect {"status":"ok",...}
curl -s -o /dev/null -w "%{http_code}\n" https://$DOMAIN/   # expect 200
echo | openssl s_client -connect $DOMAIN:443 -servername $DOMAIN 2>/dev/null \
  | openssl x509 -noout -issuer -dates           # issuer: Let's Encrypt
```

#### Troubleshooting

| Symptom | Fix |
| --- | --- |
| No certificate; the log shows a `challenge failed` error | Port 80 must be reachable from the internet. Re-run step 2 and check that the DNS name in the Caddyfile matches step 1 exactly. |
| `502 Bad Gateway` | The containers aren't running. Run `docker compose ps`, then `docker compose up -d` in `~/docclassify`. |
| `413` on large uploads | Check that `max_size 220MB` is in the Caddyfile, then run `sudo systemctl reload caddy`. |
| A config change has no effect | Run `sudo caddy validate ...` (8.3), then `sudo systemctl reload caddy`. |

Day-to-day commands: `sudo systemctl reload caddy` after editing the Caddyfile, `sudo journalctl -u caddy --since "1 hour ago"` for logs, and `sudo systemctl restart caddy` if it gets stuck.

### 9. Open the app

Browse to `https://docclassify-demo.eastus.cloudapp.azure.com`. The header badge should show Fast ✓. Precise shows ✓ only if you set `ANTHROPIC_API_KEY`.

### 10. Update later

```bash
cd ~/docclassify && git pull          # or re-copy the files with scp
docker compose up -d --build
```

To see logs, run `docker compose logs -f backend`. To stop everything and the Azure costs, run `az group delete --name docclassify-rg` from your machine.

---

**Notes**
- Run **one** VM (single replica). Batches live in memory, so a restart or redeploy clears batches that are in progress.
- `Standard_B2s` matches the PRD's 2-vCPU reference container. Pick a larger size if OCR is slow under load.
