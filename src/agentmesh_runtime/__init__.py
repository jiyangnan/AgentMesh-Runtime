from importlib.metadata import PackageNotFoundError, version
import re
from pathlib import Path


def _source_checkout_version() -> str | None:
    """Prefer pyproject metadata when running from an editable checkout."""

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    if not project:
        return None
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', project.group(1), re.M)
    return match.group(1) if match else None


try:
    __version__ = _source_checkout_version() or version("agentmesh-runtime")
except PackageNotFoundError:
    __version__ = "0.1.1"


__all__ = ["__version__"]
