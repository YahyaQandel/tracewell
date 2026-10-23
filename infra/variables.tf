variable "project_id" {
  description = "GCP project ID to deploy into"
  type        = string
  default     = "steam-kingdom-423821-k2"
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "tracewell"
}

variable "placeholder_image" {
  description = "Container image to deploy until the real backend exists"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "admin_email" {
  description = "Email address to grant Cloud Run Invoker + bucket admin access for the human operator"
  type        = string
  default     = "yahya.qandel@gmail.com"
}

variable "csrf_trusted_origin" {
  description = <<-EOT
    Full scheme+host of this Cloud Run service's own URL, for Django's
    CSRF_TRUSTED_ORIGINS (required for the admin login form and any other
    POST to work at all - ALLOWED_HOSTS=* is not sufficient on its own).
    Cloud Run assigns this on first service creation and it stays stable
    across redeploys, so it can't be computed from this same apply without
    a circular self-reference - the default below is this project's real,
    already-existing URL. If this service is ever recreated from scratch
    (new project, deleted and redeployed), get the new URL from
    `terraform output cloud_run_url` after the FIRST apply (it will 403 on
    POST until a second apply sets this correctly) and pass it via -var.
  EOT
  type        = string
  default     = "https://tracewell-sxsi7kqutq-uc.a.run.app"
}
