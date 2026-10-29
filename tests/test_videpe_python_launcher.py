"""Tests for videpe_python_launcher."""

import http.server
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from videpe_python_launcher import videpe_python_launcher as launcher

TOKEN = "test-token"  # noqa: S105 (not a real secret)


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    """Two data files to serve through the API."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    eeg = data_dir / "recording.edf"
    eeg.write_bytes(b"\x00EEG DATA\xff")
    mri = data_dir / "brain.nii"
    mri.write_bytes(b"MRI DATA")
    return [eeg, mri]


@pytest.fixture
def videpe_dir(tmp_path: Path) -> Path:
    """A fake VIDEPE build, plus a secret file next to it that must not be served."""
    build = tmp_path / "videpe-dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<h1>VIDEPE</h1>")
    (build / "app-config.js").write_text("window.videpeConfig = {};")
    (build / "assets" / "app.js").write_text("console.log('app');")
    (build / "assets" / "data.unknownext").write_bytes(b"blob")
    (tmp_path / "secret.txt").write_text("secret")
    return build


@pytest.fixture
def base_url(
    monkeypatch: pytest.MonkeyPatch,
    files: list[Path],
    videpe_dir: Path,
) -> Iterator[str]:
    """Run the launcher's Handler on a free local port and return its base URL."""
    monkeypatch.setattr(launcher, "FILES", files)
    monkeypatch.setattr(launcher, "TOKEN", TOKEN)
    monkeypatch.setattr(launcher, "VIDEPE_DIR", videpe_dir.resolve())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def get(url: str, token: str | None = TOKEN) -> tuple[int, str, bytes]:
    """GET a URL and return (status, content type, body), also for error responses."""
    request = urllib.request.Request(url)  # noqa: S310 (always a local http URL)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            return response.status, response.headers["Content-Type"], response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers["Content-Type"], error.read()


# --- The API ---


@pytest.mark.parametrize("token", [None, "wrong-token", ""])
@pytest.mark.parametrize("path", ["/api/session", "/api/files/0", "/api/unknown"])
def test_api_rejects_missing_or_wrong_token(base_url: str, path: str, token: str | None) -> None:
    status, _, _ = get(base_url + path, token=token)
    assert status == 401


def test_api_rejects_token_without_bearer_prefix(base_url: str) -> None:
    request = urllib.request.Request(base_url + "/api/session")  # noqa: S310
    request.add_header("Authorization", TOKEN)
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)  # noqa: S310
    assert error.value.code == 401


def test_session_lists_files(base_url: str) -> None:
    status, content_type, body = get(base_url + "/api/session")
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body) == {
        "version": 1,
        "title": "Example launch",
        "files": [
            {"name": "recording.edf", "url": "/api/files/0"},
            {"name": "brain.nii", "url": "/api/files/1"},
        ],
    }


def test_session_file_urls_serve_the_files(base_url: str, files: list[Path]) -> None:
    session = json.loads(get(base_url + "/api/session")[2])
    for entry, file in zip(session["files"], files, strict=True):
        status, content_type, body = get(base_url + entry["url"])
        assert status == 200
        assert content_type == "application/octet-stream"
        assert body == file.read_bytes()


def test_session_with_no_files(base_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "FILES", [])
    status, _, body = get(base_url + "/api/session")
    assert status == 200
    assert json.loads(body)["files"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/files/2",  # one past the last file
        "/api/files/99",
        "/api/files/-1",
        "/api/files/abc",
        "/api/files/",
        "/api/files/0/extra",
        "/api/unknown",
    ],
)
def test_api_unknown_paths_return_404(base_url: str, path: str) -> None:
    status, _, _ = get(base_url + path)
    assert status == 404


# --- Serving VIDEPE ---


def test_app_config_enables_host_app_mode(base_url: str) -> None:
    status, content_type, body = get(base_url + "/videpe/app-config.js", token=None)
    assert status == 200
    assert content_type == "text/javascript"
    prefix = "window.videpeConfig = "
    text = body.decode()
    assert text.startswith(prefix)
    assert text.endswith(";")
    config = json.loads(text.removeprefix(prefix).removesuffix(";"))
    assert config == {"hostApp": {"name": launcher.APP_NAME, "apiBase": "/api"}}


def test_app_config_name_is_not_empty() -> None:
    # VIDEPE ignores the hostApp section when the name is empty
    assert launcher.APP_NAME.strip()


@pytest.mark.parametrize("path", ["/videpe/", "/videpe/index.html"])
def test_serves_index_html(base_url: str, path: str) -> None:
    status, content_type, body = get(base_url + path, token=None)
    assert status == 200
    assert content_type == "text/html"
    assert body == b"<h1>VIDEPE</h1>"


def test_serves_index_html_with_query_string(base_url: str) -> None:
    status, _, body = get(base_url + f"/videpe/?token={TOKEN}", token=None)
    assert status == 200
    assert body == b"<h1>VIDEPE</h1>"


def test_serves_assets_with_content_type(base_url: str) -> None:
    status, content_type, body = get(base_url + "/videpe/assets/app.js", token=None)
    assert status == 200
    assert content_type in {"text/javascript", "application/javascript"}
    assert body == b"console.log('app');"


def test_unknown_file_type_is_served_as_octet_stream(base_url: str) -> None:
    status, content_type, body = get(base_url + "/videpe/assets/data.unknownext", token=None)
    assert status == 200
    assert content_type == "application/octet-stream"
    assert body == b"blob"


@pytest.mark.parametrize(
    "path",
    [
        "/videpe/missing.js",
        "/videpe/assets",  # a directory, not a file
        "/videpe/assets/",
        "/videpe",  # without the trailing slash
        "/",
        "/index.html",
        "/other/index.html",
    ],
)
def test_unknown_paths_return_404(base_url: str, path: str) -> None:
    status, _, _ = get(base_url + path, token=None)
    assert status == 404


@pytest.mark.parametrize(
    "path",
    [
        "/videpe/%2e%2e/secret.txt",
        "/videpe/..%2fsecret.txt",
        "/videpe/assets/%2e%2e/%2e%2e/secret.txt",
    ],
)
def test_no_paths_outside_videpe_dir(base_url: str, path: str) -> None:
    status, _, body = get(base_url + path, token=None)
    assert status == 404
    assert b"secret" not in body


def test_symlink_out_of_videpe_dir_is_not_served(base_url: str, videpe_dir: Path) -> None:
    link = videpe_dir / "link.txt"
    try:
        link.symlink_to(videpe_dir.parent / "secret.txt")
    except OSError:
        pytest.skip("symlinks not supported here")
    status, _, _ = get(base_url + "/videpe/link.txt", token=None)
    assert status == 404


# --- Choosing files ---


class FakeTk:
    """Stands in for tkinter.Tk, recording what the launcher does with the window."""

    instances: list["FakeTk"] = []  # noqa: RUF012

    def __init__(self) -> None:
        self.withdrawn = False
        self.destroyed = False
        FakeTk.instances.append(self)

    def withdraw(self) -> None:  # noqa: D102
        self.withdrawn = True

    def destroy(self) -> None:  # noqa: D102
        self.destroyed = True


@pytest.fixture
def fake_tk(monkeypatch: pytest.MonkeyPatch) -> type[FakeTk]:
    FakeTk.instances = []
    monkeypatch.setattr(launcher.tk, "Tk", FakeTk)
    return FakeTk


def test_choose_files_returns_selected_paths(
    monkeypatch: pytest.MonkeyPatch,
    fake_tk: type[FakeTk],
) -> None:
    titles = []

    def fake_dialog(*, title: str) -> tuple[str, ...]:
        titles.append(title)
        return ("/data/a.edf", "/data/b.nii")

    monkeypatch.setattr(launcher.filedialog, "askopenfilenames", fake_dialog)
    assert launcher.choose_files() == [Path("/data/a.edf"), Path("/data/b.nii")]
    assert len(titles) == 1
    assert "VIDEPE" in titles[0]
    # The empty main window is hidden, and cleaned up afterwards
    (window,) = fake_tk.instances
    assert window.withdrawn
    assert window.destroyed


def test_choose_files_cancelled(monkeypatch: pytest.MonkeyPatch, fake_tk: type[FakeTk]) -> None:
    monkeypatch.setattr(launcher.filedialog, "askopenfilenames", lambda **_: "")
    assert launcher.choose_files() == []
    assert fake_tk.instances[0].destroyed


# --- main() ---


class FakeServer:
    """Stands in for ThreadingHTTPServer, so main() returns instead of serving forever."""

    def __init__(self, address: tuple[str, int], handler: type) -> None:
        self.address = address
        self.handler = handler
        self.server_port = 12345
        self.served = False

    def serve_forever(self) -> None:  # noqa: D102
        self.served = True


@pytest.fixture
def fake_launch(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Replace the server, browser and popup; record what main() does with them."""
    calls: dict[str, list] = {"servers": [], "opened": [], "popups": []}

    def make_server(address: tuple[str, int], handler: type) -> FakeServer:
        server = FakeServer(address, handler)
        calls["servers"].append(server)
        return server

    def choose_files() -> list[Path]:
        calls["popups"].append(True)
        return [Path("picked.edf")]

    monkeypatch.setattr(launcher, "FILES", [])
    monkeypatch.setattr(launcher, "TOKEN", TOKEN)
    monkeypatch.setattr(launcher.http.server, "ThreadingHTTPServer", make_server)
    monkeypatch.setattr(launcher.webbrowser, "open", calls["opened"].append)
    monkeypatch.setattr(launcher, "choose_files", choose_files)
    return calls


def test_main_uses_command_line_files(
    monkeypatch: pytest.MonkeyPatch,
    fake_launch: dict[str, list],
) -> None:
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "a.edf", "dir/b.nii"])
    launcher.main()
    assert [Path("a.edf"), Path("dir/b.nii")] == launcher.FILES
    assert fake_launch["popups"] == []  # no popup when files are given


def test_main_shows_popup_without_arguments(
    monkeypatch: pytest.MonkeyPatch,
    fake_launch: dict[str, list],
) -> None:
    monkeypatch.setattr(launcher.sys, "argv", ["launcher"])
    launcher.main()
    assert fake_launch["popups"] == [True]
    assert [Path("picked.edf")] == launcher.FILES


def test_main_exits_when_no_files_selected(
    monkeypatch: pytest.MonkeyPatch,
    fake_launch: dict[str, list],
) -> None:
    monkeypatch.setattr(launcher.sys, "argv", ["launcher"])
    monkeypatch.setattr(launcher, "choose_files", list)
    with pytest.raises(SystemExit, match="No files selected"):
        launcher.main()
    # Nothing is started when there is nothing to show
    assert fake_launch["servers"] == []
    assert fake_launch["opened"] == []


def test_main_serves_locally_and_opens_videpe(
    monkeypatch: pytest.MonkeyPatch,
    fake_launch: dict[str, list],
) -> None:
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "a.edf"])
    launcher.main()
    (server,) = fake_launch["servers"]
    # Only reachable from this computer, on a port picked by the operating system
    assert server.address == ("127.0.0.1", 0)
    assert server.handler is launcher.Handler
    assert server.served
    assert fake_launch["opened"] == [f"http://127.0.0.1:12345/videpe/?token={TOKEN}"]


def test_token_is_random_and_url_safe() -> None:
    assert len(launcher.TOKEN) >= 32
    assert all(char.isalnum() or char in "-_" for char in launcher.TOKEN)
