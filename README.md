# :rocket: videpe-python-launcher

A minimal, standard-library-only Python example that shows how to launch [VIDEPE](https://github.com/VIDEPE/videpe) as a neural data file viewer from your own Python app.

## What is this for?

This repo is a working reference for running VIDEPE in **host-app mode**: your own (python) application serving VIDEPE and handing it the files to open. This allows a data platform, analysis pipeline or desktop tool to use VIDEPE as its viewer. Users see their data straight away, without locating and dragging in files themselves, and everything stays on their own computer. It follows VIDEPE's [host app integration guide](https://github.com/VIDEPE/videpe/blob/main/docs/host-app-integration.md).

[VIDEPE](https://github.com/VIDEPE/videpe) (*Visualization & Integration of Data for Epilepsy Presurgical Evaluation*) is a web-based viewer for EEG and neuroimaging data (EEG, electrode positions, MRI, PET, SPECT and meshes), developed at the Epilepsy and Brain Networks Lab at UNIGE. All processing happens in the browser and files are never uploaded. VIDEPE is for research use only; it is not a medical device.

- **VIDEPE on GitHub**: [github.com/VIDEPE/videpe](https://github.com/VIDEPE/videpe)
- **Try VIDEPE online**: [videpe.github.io/videpe](https://videpe.github.io/videpe/)

The launcher script ([src/videpe_python_launcher/videpe_python_launcher.py](src/videpe_python_launcher/videpe_python_launcher.py)):

1. Lets you pick the files to view, either as command-line arguments or through a file selection popup.
2. Starts a local HTTP server bound to `127.0.0.1` on a free port.
3. Serves the VIDEPE build under `/videpe/`, replacing its `app-config.js` to switch on host-app mode.
4. Exposes a small API under `/api/` (`/api/session` lists the files, `/api/files/<n>` serves their contents). Every API request must carry a random token that is generated fresh for each launch.
5. Opens VIDEPE in your default browser, which loads the session and shows the files.

It uses only the Python standard library (`http.server`, `tkinter`, ...), so the code is easy to read and to copy into your own app or adapt to a web framework.

## Quick Start

### 1. Get the VIDEPE build

VIDEPE is published as a Docker image (`ghcr.io/videpe/videpe`). You only need Docker to copy the built files out of it; the image is never run as a server. From the repo root:

```bash
docker create --pull always --platform linux/amd64 --name videpe ghcr.io/videpe/videpe:latest
docker cp videpe:/usr/share/nginx/html/videpe ./videpe-dist
docker rm videpe
```

- `docker create` downloads the image and prepares a container without starting it.
- `docker cp` copies the built site into `./videpe-dist`, where the launcher expects it.
- `docker rm` removes the temporary container.
- `--platform linux/amd64` is required on ARM machines (such as Apple Silicon Macs), as the image is only published for amd64. The extracted files work on any platform.
- Host-app mode needs VIDEPE **0.22.0 or later**. To pin a version, replace `latest` with a version number, for example `ghcr.io/videpe/videpe:0.22.0`.

Re-run these commands to update to a newer VIDEPE release. The `videpe-dist/` folder is by default ignored by git.

### 2. Run the launcher

Run it from the repo root, as `videpe-dist` is looked up relative to the current directory:

```bash
# pick the files in a popup
python src/videpe_python_launcher/videpe_python_launcher.py

# or pass them directly
python src/videpe_python_launcher/videpe_python_launcher.py path/to/file1 path/to/file2
```

VIDEPE opens in your browser with the selected files loaded. Stop the server with `Ctrl+C`.

### Troubleshooting

- **404 on `/videpe/`**: `videpe-dist` was not found. Check that you extracted the build and are running from the repo root.
- **VIDEPE shows its normal start screen instead of loading your files**: VIDEPE did not switch to host-app mode, so it started as the standalone app, where you add files yourself. This happens when the `hostApp` config in `app-config.js` is missing or invalid, or when the VIDEPE build is older than 0.22.0. Check the browser console for a warning and check your VIDEPE version.
- **No file popup appears**: your Python installation lacks `tkinter`. Pass the files as command-line arguments instead.
- **VIDEPE says the session version is not supported**: the `version` in the session does not match a host-app contract version this VIDEPE build supports. See [The session format](#the-session-format).

## The session format

The session is the heart of the integration: it is how your app tells VIDEPE what to open. VIDEPE fetches it once at startup with `GET /api/session` (more precisely `{apiBase}/session`), sending the header `Authorization: Bearer <token>`. Your app answers with JSON like this:

```json
{
  "version": 1,
  "title": "Patient 012 – resting state",
  "files": [
    { "name": "rec.vhdr", "url": "/api/files/0" },
    { "name": "rec.eeg", "url": "/api/files/1" },
    { "name": "sub-012_T1w.nii.gz", "url": "/api/files/2" }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `version` | yes | The version of the **host-app contract** your app follows, as a number. See below. |
| `title` | no | Shown next to the app name. An empty or non-string value is ignored. |
| `files` | yes | The files to open. May be empty, in which case VIDEPE tells the user there was nothing to open. |
| `files[].name` | yes | The file name, with its extension. VIDEPE picks the viewer from the extension, so it must be the real one (for example `.vhdr`, `.edf`, `.nii.gz`). Files of unsupported types are skipped, without being downloaded, and the user is warned. |
| `files[].url` | yes | A path on the same server, starting with `/`. VIDEPE downloads it with `GET` and the same `Authorization` header, so it must never point to another server. |

If the JSON is invalid or any file entry breaks these rules, VIDEPE rejects the whole session before downloading anything.

### Use the correct `version`

`version` is **not** the VIDEPE version. It is the version of the contract between VIDEPE and host apps: the shape of the session and the rules above. VIDEPE accepts only the contract versions it supports, and rejects any other with a message asking the user to update VIDEPE or the host app.

- The current contract version is **`1`**, supported from VIDEPE 0.22.0 on.
- The launcher sets it in one place, `SESSION_VERSION` in [videpe_python_launcher.py](src/videpe_python_launcher/videpe_python_launcher.py).
- Only change it when the [host app integration guide](https://github.com/VIDEPE/videpe/blob/main/docs/host-app-integration.md) introduces a new contract version, and update the session to match. A new contract may change fields, so bumping the number alone is not enough.

### How the launcher builds it

The launcher lists the selected files in order: the first one gets `/api/files/0`, the next `/api/files/1`, and so on. `name` is the file's own name, so the extension is preserved, and the real file paths on your computer never reach the browser. Files that belong together, such as BrainVision's `.vhdr` + `.eeg`, must all be selected and share the same base name.

## Setup Dev Environment

The launcher itself needs only Python 3.13+ and no extra packages. The steps below install the dev tools (tests, linting, type checking). Use either [UV](https://docs.astral.sh/uv/) (recommended) or pip.

### With UV

**Step 1**: Create a virtual environment

```bash
uv venv
```

**Step 2**: Activate your new environment

```bash
# on windows
.venv\Scripts\activate

# on mac / linux
source .venv/bin/activate
```

**Step 3**: Install all the cool dependencies

```bash
uv sync
```

### With pip

Requires pip 25.1 or later, for `--group` support.

**Step 1**: Create a virtual environment

```bash
python -m venv .venv
```

**Step 2**: Activate your new environment

```bash
# on windows
.venv\Scripts\activate

# on mac / linux
source .venv/bin/activate
```

**Step 3**: Install the project in editable mode, plus the dev dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -e . --group dev
```

## Checks

These are the checks CI runs on every pull request. Run them locally before pushing to get the same result:

```bash
# lint
uv run ruff check .

# formatting (drop --check to fix it)
uv run ruff format --check .

# type checking
uv run ty check

# tests, with 100% coverage required
uv run coverage run -m pytest tests && uv run coverage report
```

## Dependabot Setup

[Dependabot](https://docs.github.com/en/code-security/dependabot) keeps the dependencies up to date by opening pull requests, which CI then checks. It is configured in [.github/dependabot.yml](.github/dependabot.yml) to check weekly for:

- **Python packages** in `uv.lock`: as the launcher itself uses only the standard library, these are the dev tools (pytest, ruff, ty, ...). Commit messages start with `deps`.
- **GitHub Actions** used in [.github/workflows/](.github/workflows/). Commit messages start with `ci`.

Updates are grouped, so each check opens at most one pull request per group.

Security updates are switched on separately, in the repository settings:

1. Go to the "Settings -> Advanced Security" tab in your repository.
2. Under the "Dependabot" section enable the options you want, at least "Dependabot alerts" and "Dependabot security updates".

## References

- [Pattern](https://github.com/wyattferguson/pattern) - A modern cookiecutter template for your next Python project.

## License

Copyright (C) 2026 Jeroen Buil

Licensed under the [GNU Affero General Public License v3.0 only](LICENSE) (`AGPL-3.0-only`), the same license as [VIDEPE](https://github.com/VIDEPE/videpe).

## Contact

Created by [Jeroen Buil](https://github.com/JeroenBuil)
