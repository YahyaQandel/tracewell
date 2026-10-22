# Tracewell infra

Terraform for the GCP deployment of Tracewell. Minimum-cost setup: a
scale-to-zero Cloud Run service, a single GCS bucket for the SQLite database
file and run attachments (mounted into the container via Cloud Run's GCS
FUSE volume support), and an Artifact Registry repo to hold the backend
image once it exists.

**Note:** `infra/terraform/` also exists in this repo — a separate,
unapplied Terraform config (backend + frontend as two services, Secret
Manager secrets) written by a different session. It has never been
`apply`'d (no state file). This README and the resources below describe
what's actually live. The two trees need to be reconciled by a human
before either is extended further — don't assume this one wins.

## Live deployment

| | |
|---|---|
| GCP project | `steam-kingdom-423821-k2` ("CodeLab Nexus") |
| Region | `us-central1` |
| Cloud Run URL | https://tracewell-sxsi7kqutq-uc.a.run.app |
| Image running there now | `us-docker.pkg.dev/cloudrun/container/hello` (placeholder — see below) |
| GCS bucket | `steam-kingdom-423821-k2-tracewell-data` |
| Artifact Registry repo | `tracewell` (`us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell`) |
| Runtime service account | `tracewell-run@steam-kingdom-423821-k2.iam.gserviceaccount.com` |

## Why a placeholder image

At the time this infra was provisioned, Tracewell's backend (Django API +
dashboard) had not been built yet — only the `cli/` uploader existed. The
Cloud Run service, bucket, IAM, and registry are real and live now so the
pipeline work (TW-2 onward) has somewhere to deploy to, but the container
currently serving traffic is GCP's stock `hello` image, not the real app.

**There is no admin login yet** — that depends on the Django backend
actually shipping an auth/login system (tracked under the Organizations &
Projects epic). Once that exists, create a superuser and document its
credentials here (or, better, in a secrets manager — see below).

## Swapping in the real backend

1. Build the backend image and push it to the Artifact Registry repo above:
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   docker build -t us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest ./backend
   docker push us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest
   ```
2. Point Django's `DATABASES` at `/data/db.sqlite3` and `MEDIA_ROOT` at
   `/data/media` — the GCS bucket is mounted at `/data` inside the
   container (see the `volume_mounts` / `volumes` blocks in `main.tf`).
   SQLite over GCS FUSE has single-writer semantics; this is fine for a
   low-traffic instance but don't raise `max_instance_count` above 1
   without moving to Cloud SQL first.
3. Update `placeholder_image` in a `terraform.tfvars` (or pass
   `-var`) to the pushed image tag, then:
   ```bash
   terraform apply -var="placeholder_image=us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest"
   ```
4. Once Django has a working login, create the admin superuser:
   ```bash
   gcloud run services update tracewell --region us-central1 \
     --command="python,manage.py,createsuperuser,--noinput" \
     --set-env-vars="DJANGO_SUPERUSER_USERNAME=admin,DJANGO_SUPERUSER_EMAIL=you@example.com,DJANGO_SUPERUSER_PASSWORD=<generate one, don't commit it>"
   ```
   Don't commit the generated password to this README — store it in a
   password manager or `gcloud secrets` and note *where* here instead.

## State

Terraform state is local only (`infra/.terraform.tfstate`, gitignored —
never commit it, it contains resource IDs). Fine for a single operator;
if more than one person starts running `terraform apply` here, move to a
GCS backend (`terraform { backend "gcs" { bucket = "..." } }`) first so
state isn't lost or clobbered.

## Cost

Everything here scales to zero when idle:
- Cloud Run: capped at 1 instance, 1 vCPU / 512Mi, `cpu_idle = true` (no
  charge while idle, no charge at all below the free tier for low traffic).
- GCS bucket: Standard class, single region, 90-day delete lifecycle rule
  on objects — pennies/month at this scale.
- Artifact Registry: free tier covers a handful of small images.

Expect close to $0/month until this gets real sustained traffic.

## Re-running

```bash
cd infra
terraform init
gcloud auth login yahya.qandel@gmail.com   # if not already active
GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token --account=yahya.qandel@gmail.com) \
  terraform plan -out=tfplan
GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token --account=yahya.qandel@gmail.com) \
  terraform apply tfplan
```

The `GOOGLE_OAUTH_ACCESS_TOKEN` override is needed because this machine's
Application Default Credentials are logged into a different Google account
than the one that owns this GCP project; using the already-authenticated
`gcloud` CLI session sidesteps a second interactive login. If you'd rather
fix ADC itself: `gcloud auth application-default login` as
`yahya.qandel@gmail.com`, then drop the env var override.
