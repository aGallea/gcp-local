"""SPA static-file payload (built by ``npm run build``).

Production wheels and the Docker image ship the built bundle under
``static/``. Editable installs run ``cd web && npm run build`` to produce it
locally; until they do, ``/ui/`` returns a friendly fallback page from
``admin_api`` instead of crashing.
"""

from importlib.resources import files
from pathlib import Path


def static_dir() -> Path:
    """Return the directory containing the built SPA, if any.

    Honours the ``GCP_LOCAL_UI_STATIC_DIR`` env var for tests and dev.
    """
    import os

    override = os.environ.get("GCP_LOCAL_UI_STATIC_DIR")
    if override:
        return Path(override)
    return Path(str(files("gcp_local.ui").joinpath("static")))
