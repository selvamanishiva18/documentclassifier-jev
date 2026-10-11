variable "aws_region" {
  description = "AWS region for every resource."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for resources, ECR repositories and the SSM parameter path."
  type        = string
  default     = "docclassify"
}

variable "instance_type" {
  description = "EC2 size. t3.medium (2 vCPU / 4 GB) matches the PRD's 2-vCPU reference container."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "Root disk size; holds Docker images (the backend image with Tesseract is about 600 MB)."
  type        = number
  default     = 30
}

variable "domain_name" {
  description = "Your domain, e.g. docs.example.com. Leave empty to use <elastic-ip>.sslip.io, which works with HTTPS but no custom name."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Optional Route 53 hosted zone ID. If set together with domain_name, Terraform creates the A record."
  type        = string
  default     = ""
}
