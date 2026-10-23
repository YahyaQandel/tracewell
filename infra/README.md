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
| Image running there now | `us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest` — the real Django backend, deployed and live |
| GCS bucket | `steam-kingdom-423821-k2-tracewell-data` |
| Artifact Registry repo | `tracewell` (`us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell`) |
| Runtime service account | `tracewell-run@steam-kingdom-423821-k2.iam.gserviceaccount.com` |

## Deploying a new backend image

Every time a story merges to `main`, rebuild and redeploy:

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
cd backend
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest .
docker push us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest
cd ../infra
GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token --account=yahya.qandel@gmail.com) \
  terraform apply -var="placeholder_image=us-central1-docker.pkg.dev/steam-kingdom-423821-k2/tracewell/backend:latest"
```

Cloud Run pulls the image fresh on each `terraform apply` even when the
tag (`:latest`) doesn't change in the Terraform diff itself — Cloud Run
resolves `:latest` to its current digest at deploy time, so a rebuilt-
and-repushed `:latest` does get picked up. The Dockerfile's `CMD` runs
`python manage.py migrate --noinput` before starting gunicorn, so schema
migrations apply automatically on every deploy.

SQLite over GCS FUSE has single-writer semantics (and FUSE's buffered
writes can emit benign `OutOfOrderError` log lines on the journal file,
observed during normal operation) — fine for a low-traffic instance, but
don't raise `max_instance_count` above 1 without moving to Cloud SQL first.

## Admin access

A Django superuser was created via a one-off Cloud Run Job (`gcloud run
jobs create ... --command python --args manage.py,createsuperuser,--noinput`
with `DJANGO_SUPERUSER_*` env vars, then `execute`d once and deleted —
nothing superuser-related is committed here). Log in at
`https://tracewell-sxsi7kqutq-uc.a.run.app/admin/`; the password was
shown once at creation time and is not recoverable from this repo — if
lost, run the same one-off job pattern again with a fresh password to
reset it (Django's `createsuperuser --noinput` fails if the username
already exists; use `manage.py changepassword admin` via the same job
pattern instead to reset without recreating the account).
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
