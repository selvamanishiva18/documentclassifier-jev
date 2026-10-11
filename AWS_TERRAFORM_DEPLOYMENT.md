# Deploy to AWS with Terraform and GitHub Actions

Terraform builds the AWS setup from [AWS_DEPLOYMENT.md](AWS_DEPLOYMENT.md): one EC2 instance running docker compose, with Caddy for HTTPS. The `.github/workflows/deploy.yml` workflow then deploys on every push to `main`. The same workflow can deploy to **Vercel** instead; you choose the target with one setting.

---

## How it works

```
 push to main ─┐
               ├─► resolve-target ──► DEPLOY_TARGET = vercel ──► vercel job: vercel deploy --prod
 manual run ───┘     (input or            │
                      repo variable)      └─► DEPLOY_TARGET = aws ──► aws job:
                                                1. terraform apply      (EC2, Elastic IP, ECR, IAM, security group)
                                                2. keys → SSM Parameter Store (encrypted, never in Terraform state)
                                                3. build + push images  → ECR (tags: commit SHA and latest)
                                                4. SSM Run Command      → /opt/docclassify/deploy.sh <sha>
                                                5. smoke test           → https://<site>/api/health

 On the instance:  Browser ─HTTPS─► Caddy :443 ─┬─ /api/* ─► backend:8000  (X-Real-IP = visitor)
                                                └─ /*     ─► frontend:5173
```

| File | Purpose |
| --- | --- |
| `infra/aws/bootstrap/main.tf` | **One-time**, run locally. Creates the S3 bucket for Terraform state and the IAM role GitHub assumes through OIDC, so no AWS access keys are stored in GitHub. |
| `infra/aws/*.tf` | The app infrastructure: EC2 (Ubuntu 24.04, t3.medium), Elastic IP, security group (80/443 only, no SSH), ECR repos, instance role, optional Route 53 record. |
| `infra/aws/user_data.sh.tpl` | First boot: installs Docker and writes `docker-compose.yml`, `Caddyfile` and `deploy.sh` to `/opt/docclassify`. |
| `.github/workflows/deploy.yml` | Chooses AWS or Vercel, then runs that target's job. |

---

## Setup (once)

### 1. Install the tools on your machine

Install [Terraform ≥ 1.10](https://developer.hashicorp.com/terraform/install) and the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), then sign in with an admin profile: `aws configure` or `aws sso login`.

### 2. Run the bootstrap (state bucket + GitHub OIDC role)

```bash
cd infra/aws/bootstrap
cp terraform.tfvars.example terraform.tfvars    # set github_repo = "your-org/your-repo"
terraform init
terraform apply
```

The outputs give you `aws_role_arn` and `tf_state_bucket`, which you need in step 3.

- If the account already has a GitHub OIDC provider, apply fails with `EntityAlreadyExists`. Set `create_oidc_provider = false` and apply again.
- The role trusts only workflows on the `main` branch of your repo.

### 3. Add GitHub secrets and variables

In the repo, open **Settings → Secrets and variables → Actions**.

| Kind | Name | Value | Needed for |
| --- | --- | --- | --- |
| Variable | `DEPLOY_TARGET` | `aws` or `vercel`; unset means `vercel` | push deploys |
| Secret | `AWS_ROLE_ARN` | `aws_role_arn` output from step 2 | AWS |
| Variable | `TF_STATE_BUCKET` | `tf_state_bucket` output from step 2 | AWS |
| Secret | `TYPESAFE_API_KEY` | your Jev key | AWS |
| Secret | `ANTHROPIC_API_KEY` | optional; enables Precise mode | AWS |
| Variable | `AWS_REGION` | optional, default `us-east-1`; must match the bootstrap region | AWS |
| Variable | `AWS_PROJECT` | optional, default `docclassify`; must match the bootstrap `project` | AWS |
| Variable | `AWS_INSTANCE_TYPE` | optional, default `t3.medium` | AWS |
| Variable | `AWS_DOMAIN_NAME` | optional, e.g. `docs.example.com`; empty means `<ip>.sslip.io` | AWS |
| Variable | `AWS_ROUTE53_ZONE_ID` | optional; if set, Terraform creates the DNS record | AWS |
| Secret | `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | as before | Vercel |

For Vercel, the app's keys stay in the Vercel project settings, as before.

### 4. Deploy

- **Automatically:** push to `main`. The workflow deploys to `DEPLOY_TARGET`.
- **Manually:** go to **Actions → Deploy (production) → Run workflow**, then choose:
  - `target`: `aws` or `vercel`;
  - `terraform_action` (AWS only): `plan` previews changes, `apply` deploys, `destroy` removes everything.

The first AWS run takes about 8–10 minutes: the instance boots and the backend image is built. Later runs take a few minutes thanks to the build cache. The app URL appears in the run summary and in the `site_url` output.

---

## Choosing a domain

| `AWS_DOMAIN_NAME` | `AWS_ROUTE53_ZONE_ID` | Result |
| --- | --- | --- |
| empty | empty | `https://<elastic-ip-with-dashes>.sslip.io`. Works immediately with a real certificate. |
| `docs.example.com` | your zone ID | Terraform creates the `A` record. |
| `docs.example.com` | empty | Create the `A` record yourself, pointing to the `public_ip` output. Caddy retries until the record resolves. |

---

## Day-to-day

**Open a shell on the instance** (no SSH needed):

```bash
aws ssm start-session --target <instance_id>
# then, inside the session:
sudo -i
cd /opt/docclassify
```

The [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) must be installed on your machine.

**Useful commands on the instance:**
- logs: `docker compose logs -f backend`;
- status: `docker compose ps`;
- redeploy the current images: `./deploy.sh latest`.

**Rotate a key:** update the GitHub secret, then re-run the workflow. Every run writes the keys to SSM again and rewrites `.env`.

**Run Terraform locally:** use the same backend settings as the workflow.

```bash
cd infra/aws
terraform init -backend-config="bucket=<TF_STATE_BUCKET>" -backend-config="key=docclassify/terraform.tfstate" \
  -backend-config="region=us-east-1" -backend-config="encrypt=true" -backend-config="use_lockfile=true"
terraform plan
```

**Remove everything:**
1. Run the workflow with `target=aws` and `terraform_action=destroy`. This also deletes the SSM keys.
2. Optionally remove the bootstrap: in `infra/aws/bootstrap`, run `terraform destroy`. Empty the state bucket first; it is versioned.

---

## Notes and limits

- **Single instance on purpose.** Batches live in memory (PRD), so a redeploy clears batches that are in progress. Don't put this behind an Auto Scaling group.
- **Some config changes replace the instance.** Changing `AWS_INSTANCE_TYPE`, the domain, or `user_data.sh.tpl` makes Terraform replace the instance, and the workflow redeploys the app straight away. The Elastic IP stays the same. Each new instance requests a fresh certificate, and Let's Encrypt allows 5 identical certificates per week, so avoid replacing the instance repeatedly.
- **Security.**
  - The security group exposes only ports 80 and 443; port 22 isn't open.
  - The instance requires IMDSv2.
  - The disk is encrypted.
  - The keys live in SSM as `SecureString` and are written to `/opt/docclassify/.env`, readable by root only.
  - The deploy role has `PowerUserAccess` plus IAM rights limited to `docclassify-app-*` roles. Tighten it further if your organisation requires that.
- **Cost (us-east-1, approximate):** about $30 a month for the t3.medium, plus about $3.60 for the Elastic IP, plus a few dollars for disk and ECR storage.
- **Why Vercel doesn't use Terraform.** The Vercel job uses the Vercel CLI instead. Vercel builds the container services from `vercel.json` on every deploy, so there's no infrastructure for Terraform to provision. The Vercel caveats in `DECISIONS.md` still apply: in-memory batches and the request-size limit.
