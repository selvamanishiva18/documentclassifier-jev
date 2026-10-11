output "site_url" {
  value = "https://${local.site_address}"
}

output "public_ip" {
  description = "Point your domain's A record here if Terraform doesn't manage DNS."
  value       = aws_eip.app.public_ip
}

output "instance_id" {
  value = aws_instance.app.id
}

output "ecr_registry" {
  value = local.registry
}

output "ecr_backend_url" {
  value = aws_ecr_repository.app["backend"].repository_url
}

output "ecr_frontend_url" {
  value = aws_ecr_repository.app["frontend"].repository_url
}

output "ssm_parameter_prefix" {
  description = "API keys are stored as SecureString parameters under this path."
  value       = local.param_prefix
}
