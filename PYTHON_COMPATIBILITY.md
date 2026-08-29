# Python compatibility

This project is pinned to Python 3.12.7 across all deployment paths.

- Project metadata: `pyproject.toml` -> `requires-python = ">=3.12,<3.13"`
- Render Blueprint: `render.yaml` -> `PYTHON_VERSION=3.12.7`
- Local/fallback runtime hint: `runtime.txt` -> `python-3.12.7`

Why pinned instead of a range: pandas/pykrx and other binary-dependent
packages this project relies on do not always have pre-built wheels
available for the newest Python releases immediately after they ship.
Allowing a wide version range (e.g. 3.11–3.15) means Render can pick a
version at build time for which no wheel exists yet, causing the build
(and therefore the boot) to fail intermittently and unpredictably.

If deploying through an existing Render service instead of a Blueprint,
make sure the service environment variable `PYTHON_VERSION` is also set
to `3.12.7` — otherwise Render may fall back to a different default and
reintroduce this same failure mode.

To upgrade the pinned version in the future, update all three files
above together and confirm pandas/pykrx publish wheels for the new
version before merging.
