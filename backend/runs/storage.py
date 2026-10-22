"""Attachment filesystem layout: backend/media/runs/<run.id>/<attachment uuid>-<name>.

The actual upload_to path is on Attachment.file (see models.py's
attachment_upload_path) since Django's FileField needs the path at
save-time, when the Attachment instance (and therefore its run id) already
exists. This module exists so design.md's module layout has a storage.py
to describe the layout in one place, even though the path logic itself
lives on the model (Django's upload_to convention).
"""
from runs.models import attachment_upload_path  # noqa: F401  (re-exported for discoverability)
