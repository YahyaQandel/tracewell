provider "google" {
  project = var.project_id
  region  = var.region
}

# --- APIs -------------------------------------------------------------

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  project            = var.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "storage" {
  project            = var.project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  project            = var.project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

# --- Artifact Registry (holds the real backend image once it exists) --

resource "google_artifact_registry_repository" "tracewell" {
  project       = var.project_id
  location      = var.region
  repository_id = "tracewell"
  format        = "DOCKER"
  description   = "Tracewell backend container images"

  depends_on = [google_project_service.artifact_registry]
}

# --- GCS bucket for SQLite db file + run attachments -------------------
# Mounted into the Cloud Run container via Cloud Run's GCS FUSE volume
# support. Single region, no versioning, lowest-cost storage class —
# this is a low-traffic app, not a high-durability data store.

resource "google_storage_bucket" "data" {
  project                     = var.project_id
  name                        = "${var.project_id}-tracewell-data"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.storage]
}

# --- Service account the Cloud Run service runs as ---------------------

resource "google_service_account" "run_sa" {
  project      = var.project_id
  account_id   = "tracewell-run"
  display_name = "Tracewell Cloud Run runtime"
}

resource "google_storage_bucket_iam_member" "run_sa_bucket_access" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.run_sa.email}"
}

# --- Cloud Run service ---------------------------------------------------
# Scale-to-zero, single small instance cap, placeholder image until the
# real Django backend lands via the TW-2+ pipeline work.

resource "google_cloud_run_v2_service" "tracewell" {
  project  = var.project_id
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.run_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.placeholder_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      volume_mounts {
        name       = "data"
        mount_path = "/data"
      }
    }

    volumes {
      name = "data"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
      }
    }
  }

  depends_on = [google_project_service.run]
}

# Allow unauthenticated access (public dashboard) — revisit once auth exists.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.tracewell.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "admin_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.tracewell.name
  role     = "roles/run.developer"
  member   = "user:${var.admin_email}"
}
