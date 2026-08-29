# Python compatibility

This project supports Python 3.11, 3.12, 3.13, and 3.14.

- Project metadata: `pyproject.toml` -> `requires-python = ">=3.11,<3.15"`
- Render Blueprint: `PYTHON_VERSION=3.14.3`
- `runtime.txt` remains at `python-3.12.7` as a local/fallback runtime hint.

If deploying through an existing Render service instead of a Blueprint, set the service environment variable `PYTHON_VERSION` to a fully qualified supported version (for example `3.14.3`).
