# Single EC2 instance running backend + frontend + Caddy with docker compose.
# One instance on purpose: batches live in memory (PRD), so the app must not be scaled out.
# Images come from ECR; the deploy workflow pushes them and then runs /opt/<project>/deploy.sh over SSM.

data "aws_caller_identity" "current" {}

data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  registry     = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  param_prefix = "/${var.project}"
  # Without a custom domain, sslip.io maps 1-2-3-4.sslip.io to 1.2.3.4, so Caddy can still get a certificate.
  site_address = var.domain_name != "" ? var.domain_name : "${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"
}

# ---- Container registries --------------------------------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  for_each             = toset(["backend", "frontend"])
  name                 = "${var.project}-${each.key}"
  image_tag_mutability = "MUTABLE" # `latest` is re-pointed on every deploy
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# ---- Network ---------------------------------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "app" {
  name        = "${var.project}-web"
  description = "HTTP/HTTPS to Caddy only. No SSH: use SSM Session Manager."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (Let's Encrypt check + redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Image pulls, Jev / Anthropic APIs, Let's Encrypt"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "${var.project}-app" }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

resource "aws_route53_record" "app" {
  count   = var.domain_name != "" && var.route53_zone_id != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

# ---- Instance role: SSM agent, ECR pulls, read the API keys ----------------------------------------------------

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project}-app-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

data "aws_iam_policy_document" "read_keys" {
  statement {
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${local.param_prefix}/*"]
  }
}

resource "aws_iam_role_policy" "read_keys" {
  name   = "read-api-keys"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_keys.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project}-app-instance"
  role = aws_iam_role.app.name
}

# ---- Instance --------------------------------------------------------------------------------------------------

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.ubuntu_ami.insecure_value
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    project      = var.project
    region       = var.aws_region
    registry     = local.registry
    param_prefix = local.param_prefix
    site_address = local.site_address
  })
  # A changed compose file or Caddyfile means a fresh instance; the workflow redeploys the app right after.
  user_data_replace_on_change = true

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }

  tags = { Name = "${var.project}-app" }

  lifecycle {
    # Canonical publishes new AMIs often; don't replace the instance every time it does.
    ignore_changes = [ami]
  }
}
