# Python compatibility

This project is pinned to Python 3.12.7 across all deployment paths.

## Render actually reads these (in order of precedence)

1. The service's `PYTHON_VERSION` environment variable — set in `render.yaml`
   (applies automatically only when deployed via **Render Blueprint sync**).
   If this service was instead created manually and connected to GitHub
   directly (not through "New + → Blueprint"), `render.yaml`'s `envVars`
   are **not** applied automatically — you must set `PYTHON_VERSION=3.12.7`
   by hand in the Render Dashboard → your service → Environment tab.
2. A `.python-version` file at the repo root (this repo has one, pinned to
   `3.12.7`). Render falls back to this if `PYTHON_VERSION` isn't set.

## What NOT to rely on

`runtime.txt` is a **Heroku** convention. Render's Python buildpack does
not read it at all — it has no effect on which Python version gets used,
and its presence can be actively misleading (a previous version of this
project kept `runtime.txt` and `render.yaml` "in sync" while actual builds
ignored `runtime.txt` completely and picked whatever Render's org-wide
default was). This repo does not include a `runtime.txt` file anymore —
don't re-add one expecting it to pin the version.

`pyproject.toml` -> `requires-python = ">=3.12,<3.13"` doesn't select a
Python version either — it only makes `pip install` refuse to proceed if
the *already-selected* interpreter isn't 3.12.x, which is what turns a
silent wrong-version build into a loud, obvious failure instead.

## Why pinned instead of a wide range

pandas/pykrx and other binary-dependent packages this project relies on
do not always have pre-built wheels available for the newest Python
releases immediately after they ship. If Render silently picks up its
latest default (e.g. 3.14.x) because neither `PYTHON_VERSION` nor
`.python-version` actually took effect, the build can fail — or worse,
succeed with a slightly different dependency resolution than what was
tested locally.

## To upgrade the pinned version later

Update **both** `.python-version` and `render.yaml`'s `PYTHON_VERSION`
together, confirm pandas/pykrx publish wheels for the new version, and
if deploying to an existing (non-Blueprint) Render service, also update
the `PYTHON_VERSION` value directly in the Render Dashboard.
