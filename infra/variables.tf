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
