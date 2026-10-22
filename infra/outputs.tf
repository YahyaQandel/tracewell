output "cloud_run_url" {
  description = "Public URL of the Tracewell Cloud Run service"
  value       = google_cloud_run_v2_service.tracewell.uri
}

output "bucket_name" {
  description = "GCS bucket backing SQLite + run attachments"
  value       = google_storage_bucket.data.name
}

output "artifact_registry_repo" {
  description = "Artifact Registry repo to push the real backend image to"
  value       = google_artifact_registry_repository.tracewell.name
}

output "run_service_account" {
  description = "Service account the Cloud Run service runs as"
  value       = google_service_account.run_sa.email
}
