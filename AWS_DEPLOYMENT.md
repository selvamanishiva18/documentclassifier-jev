# Deploy on AWS EC2 (manual)

The app runs on a single Ubuntu EC2 instance with the existing `docker-compose.yml`, and Caddy in front adds HTTPS. A single instance matches the PRD's single-replica, in-memory design, so no code changes are needed.

> Prefer automation? [AWS_TERRAFORM_DEPLOYMENT.md](AWS_TERRAFORM_DEPLOYMENT.md) builds the same setup with Terraform and deploys from GitHub Actions.

**You need:**
- an AWS account and the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), already set up with `aws configure`;
- a bash shell (Linux, macOS, WSL, or Git Bash on Windows);
- your `TYPESAFE_API_KEY`. `ANTHROPIC_API_KEY` is optional; set it to enable Precise mode.

Steps 1–3 run **on your machine**, and they must run in the **same terminal** because they share shell variables.

---

### 1. Create a security group (web ports open, SSH from your IP only)

```bash
export AWS_REGION=us-east-1
MY_IP=$(curl -s https://checkip.amazonaws.com)
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)

SG_ID=$(aws ec2 create-security-group --group-name docclassify-web \
  --description "docclassify: HTTP/HTTPS + SSH from admin IP" --vpc-id "$VPC_ID" \
  --query GroupId --output text)

aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
  "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
  "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" \
  "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MY_IP/32}]"
```

Ports 8000 and 5173 stay closed to the internet; only Caddy is public.

### 2. Launch the instance (t3.medium = 2 vCPU / 4 GB, Ubuntu 24.04)

```bash
aws ec2 create-key-pair --key-name docclassify-key --query KeyMaterial --output text > docclassify-key.pem
chmod 400 docclassify-key.pem

AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)

INSTANCE_ID=$(aws ec2 run-instances --image-id "$AMI_ID" --instance-type t3.medium \
  --key-name docclassify-key --security-group-ids "$SG_ID" \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,Encrypted=true}' \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=docclassify}]' \
  --query 'Instances[0].InstanceId' --output text)

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
```

Keep `docclassify-key.pem` somewhere safe. `.gitignore` already excludes `*.pem`.

### 3. Give it a fixed IP and a domain name

```bash
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"
PUBLIC_IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text)
echo "Public IP: $PUBLIC_IP"
```

Caddy needs a domain name to get an HTTPS certificate. Let's Encrypt won't issue one for the default `ec2-…amazonaws.com` names. Choose one option:

- **Your own domain (recommended):** create a DNS `A` record, for example `docs.example.com`, pointing to `$PUBLIC_IP`.
- **No domain:** use sslip.io, a free service that maps `1-2-3-4.sslip.io` to the IP `1.2.3.4`:
  ```bash
  echo "$(echo "$PUBLIC_IP" | tr . -).sslip.io"
  ```

Write down your domain; the rest of this guide calls it `DOMAIN`.

### 4. Connect to the instance

```bash
ssh -i docclassify-key.pem ubuntu@$PUBLIC_IP
```

All remaining steps run **on the instance**.

### 5. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

### 6. Get the code

Clone the repo:

```bash
git clone https://github.com/<your-org>/<your-repo>.git docclassify && cd docclassify
```

No repo? Copy the code from your machine instead. Run this on **your machine**, from the folder containing the project:

```bash
scp -i docclassify-key.pem -r DocumentExtractor ubuntu@<PUBLIC_IP>:~/docclassify
```

Then `cd ~/docclassify` on the instance.

### 7. Add your keys and start the app

```bash
cp .env.example .env
nano .env          # set TYPESAFE_API_KEY=... (and ANTHROPIC_API_KEY=... for Precise mode)
chmod 600 .env

docker compose up -d --build
curl -s http://localhost:8000/api/health
```

The health check should return `"status":"ok"` and `"tesseract":true`. Containers restart automatically after a reboot (`restart: unless-stopped`).

### 8. Turn on HTTPS with Caddy

Caddy is the only public entry point. It:
- gets and renews a Let's Encrypt certificate automatically;
- redirects `http://` to `https://`;
- sends `/api/*` straight to the backend, with the visitor's real IP in `X-Real-IP`, which the limit of 30 uploads per hour per IP depends on;
- sends everything else to the frontend;
- allows uploads up to 220 MB.

```
                      EC2 instance (security group: 80/443 public, 22 admin IP only)
 ┌──────────┐  HTTPS  ┌──────────────────────────────────────────────────────────┐
 │ Browser  │────────►│  Caddy (systemd, :80 → redirect, :443 TLS)               │
 └──────────┘         │     ├── /api/* ──► localhost:8000 ─► backend container   │
                      │     └── /*     ──► localhost:5173 ─► frontend container  │
                      └──────────────────────────────────────────────────────────┘
First start: Caddy ──► Let's Encrypt (HTTP check on port 80) ──► certificate in /var/lib/caddy
```

**8.1 Install Caddy** from its official repository:

```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy
```

**8.2 Write the Caddyfile.** Replace `DOMAIN` with your domain from step 3:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
DOMAIN {
    request_body {
        max_size 220MB
    }
    encode zstd gzip
    handle /api/* {
        reverse_proxy localhost:8000 {
            header_up X-Real-IP {remote_host}
        }
    }
    handle {
        reverse_proxy localhost:5173
    }
}
EOF
```

**8.3 Validate, apply, and start on boot:**

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile   # expect "Valid configuration"
sudo systemctl enable caddy && sudo systemctl reload caddy
sudo journalctl -u caddy -f      # wait for "certificate obtained successfully", then Ctrl+C
```

**8.4 Verify:**

```bash
DOMAIN=docs.example.com                                   # your domain
curl -sI http://$DOMAIN | head -n 3                       # expect 308 redirect to https://
curl -s https://$DOMAIN/api/health                        # expect {"status":"ok",...}
```

| Symptom | Fix |
| --- | --- |
| Log shows `challenge failed` | Port 80 must be open (step 1), and the DNS record must point to the Elastic IP (step 3). |
| `502 Bad Gateway` | Containers aren't running: in `~/docclassify`, run `docker compose ps`, then `docker compose up -d`. |
| `413` on large uploads | Check `max_size 220MB` in the Caddyfile, then run `sudo systemctl reload caddy`. |

### 9. Open the app

Browse to `https://DOMAIN`. The header badge should show Fast ✓. Precise shows ✓ only if you set `ANTHROPIC_API_KEY`.

### 10. Update later, or remove everything

To update, run this on the instance:

```bash
cd ~/docclassify && git pull          # or re-copy the files with scp
docker compose up -d --build
```

To see logs, run `docker compose logs -f backend`.

To remove everything and stop the charges, run this on **your machine** in the terminal from steps 1–3:

```bash
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID"
aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"
aws ec2 release-address --allocation-id "$ALLOC_ID"      # unattached Elastic IPs are billed
aws ec2 delete-security-group --group-id "$SG_ID"
aws ec2 delete-key-pair --key-name docclassify-key
```

---

**Notes**
- Run **one** instance (single replica). Batches live in memory, so a restart or redeploy clears batches that are in progress.
- `t3.medium` matches the PRD's 2-vCPU reference container. Pick a larger size, such as `t3.large`, if OCR is slow under load.
- Your IP changed and SSH stopped working? Re-run the port 22 rule from step 1 with the new IP. Alternatively, attach the `AmazonSSMManagedInstanceCore` role and use Session Manager with no SSH at all.
