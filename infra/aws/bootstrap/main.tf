# One-time setup, run locally by an AWS admin (see AWS_TERRAFORM_DEPLOYMENT.md, step 2).
# Creates the S3 bucket for Terraform state and the IAM role GitHub Actions assumes through OIDC.
# Uses local state on purpose: it holds no secrets and is only needed again to change or remove these two things.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { Project = var.project, ManagedBy = "terraform-bootstrap" }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  description = "Name prefix; must match the AWS_PROJECT repository variable (default docclassify)."
  type        = string
  default     = "docclassify"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name."
  type        = string
}

variable "create_oidc_provider" {
  description = "Set to false if the account already has the token.actions.githubusercontent.com OIDC provider."
  type        = bool
  default     = true
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  oidc_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : (
    "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
  )
}

# ---- Terraform state bucket ------------------------------------------------------------------------------------

resource "aws_s3_bucket" "tf_state" {
  bucket = "${var.project}-tfstate-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- GitHub Actions OIDC role ----------------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only workflows running on the main branch of this repo can assume the role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.project}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

# PowerUserAccess covers EC2, ECR, SSM, S3 and Route 53 but no IAM.
resource "aws_iam_role_policy_attachment" "power_user" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# IAM rights limited to the instance role and profile that infra/aws creates (names start with the project prefix).
data "aws_iam_policy_document" "iam_scoped" {
  statement {
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateAssumeRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/${var.project}-app-*"]
  }
  statement {
    actions = [
      "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile", "iam:TagInstanceProfile",
      "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
    ]
    resources = ["arn:aws:iam::${local.account_id}:instance-profile/${var.project}-app-*"]
  }
}

resource "aws_iam_role_policy" "iam_scoped" {
  name   = "scoped-iam"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.iam_scoped.json
}

output "aws_role_arn" {
  description = "Store as the AWS_ROLE_ARN repository secret."
  value       = aws_iam_role.github_deploy.arn
}

output "tf_state_bucket" {
  description = "Store as the TF_STATE_BUCKET repository variable."
  value       = aws_s3_bucket.tf_state.bucket
}
