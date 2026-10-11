#!/bin/bash
# First-boot setup, rendered by Terraform (templatefile). Installs Docker and writes the runtime files.
# It does not start the app: the deploy workflow pushes images to ECR first, then runs deploy.sh over SSM.
# Template note: $${...} renders as a literal $${...}; plain $VAR is left for bash.
set -euxo pipefail

apt-get update
curl -fsSL https://get.docker.com | sh # Docker Engine + compose plugin
snap install aws-cli --classic

APP_DIR=/opt/${project}
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# ---- docker-compose.yml: only Caddy publishes ports ------------------------------------------------------------
cat > docker-compose.yml <<'COMPOSE'
services:
  backend:
    image: ${registry}/${project}-backend:$${IMAGE_TAG:-latest}
    env_file: .env
    restart: unless-stopped

  frontend:
    image: ${registry}/${project}-frontend:$${IMAGE_TAG:-latest}
    depends_on:
      - backend
    restart: unless-stopped

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - backend
      - frontend
    restart: unless-stopped

volumes:
  caddy_data:
  caddy_config:
COMPOSE

# ---- Caddyfile: automatic HTTPS, /api straight to the backend with the visitor's IP (rate limiting) -------------
cat > Caddyfile <<'CADDY'
${site_address} {
	# PRD upload limit: 20 files x 10 MB + multipart overhead
	request_body {
		max_size 220MB
	}

	encode zstd gzip

	handle /api/* {
		reverse_proxy backend:8000 {
			header_up X-Real-IP {remote_host}
		}
	}

	handle {
		reverse_proxy frontend:5173
	}
}
CADDY

# ---- deploy.sh <image-tag>: run by the workflow via SSM Run Command --------------------------------------------
cat > deploy.sh <<'DEPLOY'
#!/bin/bash
set -euo pipefail
export PATH="$PATH:/snap/bin"
TAG="$1"
cd /opt/${project}

aws ecr get-login-password --region ${region} \
  | docker login --username AWS --password-stdin ${registry} > /dev/null

get_param() {
  aws ssm get-parameter --region ${region} --name "${param_prefix}/$1" --with-decryption \
    --query Parameter.Value --output text 2> /dev/null || true
}

TYPESAFE_API_KEY="$(get_param TYPESAFE_API_KEY)"
if [ -z "$TYPESAFE_API_KEY" ]; then
  echo "SSM parameter ${param_prefix}/TYPESAFE_API_KEY is missing" >&2
  exit 1
fi

# Keys go only into this root-only file; they are never echoed.
umask 077
cat > .env.new <<ENV
IMAGE_TAG=$TAG
TYPESAFE_API_KEY=$TYPESAFE_API_KEY
ANTHROPIC_API_KEY=$(get_param ANTHROPIC_API_KEY)
ALLOWED_ORIGINS=https://${site_address}
ENV
mv .env.new .env

docker compose pull --quiet
docker compose up -d --remove-orphans

# Wait for the backend's Docker HEALTHCHECK (GET /api/health).
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q backend)" 2> /dev/null || echo starting)"
  if [ "$status" = "healthy" ]; then
    docker image prune -f > /dev/null
    echo "Deployed $TAG"
    exit 0
  fi
  sleep 5
done

echo "Backend did not become healthy; recent logs:" >&2
docker compose logs --tail 50 backend >&2
exit 1
DEPLOY
chmod 700 deploy.sh
