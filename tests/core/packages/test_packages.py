import io
import json
import zipfile
from pathlib import Path

import pytest

from core import jinni_client, packages
from core.packages import dependencies, python_deps
from protocol import DeviceHealth, ServiceHealth
from tests.fakes import FakeKlipperJinni

MP = pytest.MonkeyPatch


@pytest.fixture(autouse=True)
def _healthy_printer(monkeypatch: MP) -> None:
    """Default the HTTP boundary to a healthy printer so a core-service restart's safety check
    passes without real network. A test wanting a broken printer overrides urlopen itself."""
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: _HealthyServerInfo())


class _HealthyServerInfo:
    """A urllib response double: a healthy Moonraker /server/info with no failed components."""

    def __enter__(self) -> "_HealthyServerInfo":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"result": {"klippy_state": "ready", "failed_components": [], "warnings": []}}'


def make_zip(entries: dict[str, bytes | str]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            data = content if isinstance(content, bytes) else content.encode()
            zf.writestr(name, data)
    return buffer


def minimal_manifest(name: str = "test-plugin", extra: dict | None = None) -> str:
    base: dict = {
        "name": name,
        "version": "0.1.0",
        "install": {"dirs": [], "symlinks": [], "patches": []},
        "files": [],
    }
    if extra:
        base.update(extra)
    return json.dumps(base)


def test_install_extracts_to_plugin_subdir(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "test-plugin.b3"
    zip_path.write_bytes(make_zip({"manifest.json": minimal_manifest()}).getvalue())

    plugin_id, _log = packages.install(zip_path, {})

    assert plugin_id == "test-plugin"
    assert (tmp_path / "test-plugin" / "manifest.json").exists()


def test_install_emits_each_phase_to_on_phase_in_log_order(tmp_path: Path, monkeypatch: MP) -> None:
    # The live-progress feed relies on on_phase firing once per phase, in the same order the phases
    # land in the returned log, starting with extract.
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "test-plugin.b3"
    zip_path.write_bytes(make_zip({"manifest.json": minimal_manifest()}).getvalue())
    seen: list[dict] = []

    _plugin_id, log = packages.install(zip_path, {}, on_phase=seen.append)

    assert [phase["id"] for phase in seen] == [phase["id"] for phase in log]
    assert seen[0]["id"] == "extract"


def test_install_excludes_doc_from_printer(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "doc-plugin.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": minimal_manifest("doc-plugin"),
        "files/x.cfg": "data",
        "doc/README.md": "# docs",
        "doc/images/shot.png": b"not-really-a-png",
    }).getvalue())

    packages.install(zip_path, {})

    plugin_dir = tmp_path / "doc-plugin"
    assert (plugin_dir / "files" / "x.cfg").exists()
    assert not (plugin_dir / "doc").exists()


def test_reconfigure_rerenders_template(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    manifest = minimal_manifest("cfg-plugin", extra={
        "install": {
            "dirs": [], "symlinks": [], "patches": [], "start": [],
            "templates": [{"from": "files/conf.tmpl", "to": "files/conf.cfg"}],
        },
    })
    zip_path = tmp_path / "cfg-plugin.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest,
        "files/conf.tmpl": "mode: $MODE\n",
    }).getvalue())

    packages.install(zip_path, {"MODE": "auto"}, user_vars={"MODE": "auto"})
    rendered = tmp_path / "cfg-plugin" / "files" / "conf.cfg"
    assert rendered.read_text() == "mode: auto\n"

    packages.reconfigure("cfg-plugin", {"MODE": "manual"}, {"MODE": "manual"})
    assert rendered.read_text() == "mode: manual\n"


def test_reconfigure_unknown_plugin_raises(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    with pytest.raises(ValueError):
        packages.reconfigure("nope", {}, {})


def test_install_raises_when_manifest_is_missing(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "bad.b3"
    zip_path.write_bytes(make_zip({"other-file.txt": "content"}).getvalue())

    with pytest.raises(ValueError, match="missing manifest.json"):
        packages.install(zip_path, {})


def test_install_creates_dirs(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    target_dir = tmp_path / "mydir"
    manifest = minimal_manifest(
        extra={"install": {"dirs": [str(target_dir)], "symlinks": [], "patches": []}}
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    packages.install(zip_path, {})

    assert target_dir.is_dir()


def test_install_creates_symlinks(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    src_rel = "files/myscript.py"
    dst = tmp_path / "link-target.py"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [{"from": src_rel, "to": str(dst)}],
                "patches": [],
            },
            "files": [{"path": src_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, src_rel: "# script"}).getvalue()
    )

    packages.install(zip_path, {})

    assert dst.is_symlink()


def test_install_expands_vars_in_symlink_dst(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    extras_dir = tmp_path / "extras"
    extras_dir.mkdir()
    src_rel = "files/mod.py"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [{"from": src_rel, "to": "$EXTRAS/mod.py"}],
                "patches": [],
            },
            "files": [{"path": src_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, src_rel: "# mod"}).getvalue()
    )

    packages.install(zip_path, {"EXTRAS": str(extras_dir)})

    assert (extras_dir / "mod.py").is_symlink()


def test_uninstall_removes_plugin_dir_and_symlinks(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = tmp_path / "my-plugin"
    plugin_dir.mkdir()
    link = tmp_path / "link.py"
    link.symlink_to(plugin_dir / "files" / "mod.py")
    manifest = {
        "name": "my-plugin",
        "install": {
            "dirs": [],
            "symlinks": [{"from": "files/mod.py", "to": str(link)}],
            "patches": [],
        },
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))

    packages.uninstall("my-plugin", {})

    assert not plugin_dir.exists()
    assert not link.exists()


def test_uninstall_raises_when_plugin_does_not_exist(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)

    with pytest.raises(FileNotFoundError):
        packages.uninstall("nonexistent-plugin", {})


def test_install_replaces_dir_with_dir_symlink(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    src_rel = "files/bindir"
    dst = tmp_path / "link-bindir"
    dst.mkdir()
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [{"from": src_rel, "to": str(dst)}],
                "patches": [],
            }
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, f"{src_rel}/hello.txt": "hi"}).getvalue()
    )
    packages.install(zip_path, {})
    assert dst.is_symlink()


def test_uninstall_restores_stock_dir_displaced_by_symlink(tmp_path: Path, monkeypatch: MP) -> None:
    """A symlink shadowing a real stock directory must be backed up on install and put back on
    uninstall, so teardown never strands the printer with a missing stock path (the fluidd case)."""
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    src_rel = "files/ui"
    stock = tmp_path / "stock-ui"
    stock.mkdir()
    (stock / "stock-marker.txt").write_text("factory")
    install = {"dirs": [], "symlinks": [{"from": src_rel, "to": str(stock)}], "patches": []}
    manifest = minimal_manifest(name="ui-plugin", extra={"install": install})
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, f"{src_rel}/index.html": "modern"}).getvalue()
    )

    packages.install(zip_path, {})
    assert stock.is_symlink()

    packages.uninstall("ui-plugin", {})

    assert stock.is_dir() and not stock.is_symlink()
    assert (stock / "stock-marker.txt").read_text() == "factory"


def test_install_with_a_failing_required_patch_deactivates_and_keeps_the_log(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """A required phase that fails (a patch whose context does not match) must NOT pass as a clean
    install. The half-applied plugin is deactivated, the protection recover gives a broken plugin,
    and the install log is kept for inspection: every phase is still returned and the plugin dir
    stays on disk. It is never reported as Installed-and-working (the truthfulness violation)."""
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    stock_source = tmp_path / "klippy" / "toolhead.py"
    stock_source.parent.mkdir(parents=True)
    stock_source.write_text("real source line\n")
    mismatched_patch = (
        "--- a/toolhead.py\n+++ b/toolhead.py\n"
        "@@ -1 +1 @@\n-context that does not match\n+replacement\n"
    )
    manifest = minimal_manifest(
        "patchy",
        extra={"install": {"dirs": [], "symlinks": [],
                           "patches": [{"file": str(stock_source), "patch": "bad.patch"}]}},
    )
    zip_path = tmp_path / "patchy.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, "bad.patch": mismatched_patch}).getvalue()
    )

    _plugin_id, log = packages.install(zip_path, {})

    patch_phase = next(phase for phase in log if phase["id"] == "patches")
    assert patch_phase["ok"] is False
    assert not all(logged_phase["ok"] for logged_phase in log)
    plugin_dir = tmp_path / "patchy"
    assert (plugin_dir / "deactivated.json").exists()
    assert (plugin_dir / "manifest.json").exists()


def test_install_applies_multiple_fragments_to_one_file_cumulatively(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """Several patch fragments targeting ONE file (klipper-motion patches toolhead.py four times)
    apply in order, each building on the previous. The second fragment's context IS the first's
    result, so it applies only if the daemon accumulates on a working copy instead of re-applying
    against the pristine baseline. The final device file carries both, the phase is clean (no
    deactivate), and each fragment is its own item so a conflict pins the exact diff."""
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    stock_source = tmp_path / "klippy" / "toolhead.py"
    stock_source.parent.mkdir(parents=True)
    stock_source.write_text("alpha\n")
    first_fragment = "--- a/toolhead.py\n+++ b/toolhead.py\n@@ -1 +1 @@\n-alpha\n+beta\n"
    second_fragment = "--- a/toolhead.py\n+++ b/toolhead.py\n@@ -1 +1 @@\n-beta\n+gamma\n"
    manifest = minimal_manifest(
        "motion",
        extra={"install": {"dirs": [], "symlinks": [], "patches": [
            {"file": str(stock_source), "patch": "01.patch"},
            {"file": str(stock_source), "patch": "02.patch"},
        ]}},
    )
    zip_path = tmp_path / "motion.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest, "01.patch": first_fragment, "02.patch": second_fragment,
    }).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    patch_phase = next(phase for phase in log if phase["id"] == "patches")
    assert patch_phase["ok"] is True
    assert [patch_item["label"] for patch_item in patch_phase["items"]] == [
        "patch 01.patch", "patch 02.patch",
    ]
    assert stock_source.read_text() == "gamma\n"
    assert not (tmp_path / "motion" / "deactivated.json").exists()


def test_install_runs_start_commands(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    ran: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)  # type: ignore[arg-type]
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    manifest = minimal_manifest(
        extra={"install": {"dirs": [], "symlinks": [], "patches": [], "start": ["echo hello"]}}
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())
    packages.install(zip_path, {})
    assert "echo hello" in ran


def test_install_makes_files_executable(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": minimal_manifest(), "files/s65init.sh": "#!/bin/sh"}).getvalue()
    )

    packages.install(zip_path, {})

    script = tmp_path / "test-plugin" / "files" / "s65init.sh"
    assert script.stat().st_mode & 0o111 != 0


def test_install_intent_place_and_restart(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    ran: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)  # type: ignore[arg-type]
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    klipper_cfg_dir = tmp_path / "config" / "bespok3d" / "klipper"
    klipper_cfg_dir.mkdir(parents=True)
    src_rel = "files/cfg/klipper/cpu-temp.cfg"
    manifest = minimal_manifest(
        extra={
            "install": {
                "place": [{"class": "klipper-config", "src": src_rel}],
                "restart": ["klipper"],
            },
            "files": [{"path": src_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    entries: dict[str, bytes | str] = {"manifest.json": manifest, src_rel: "[temperature_sensor]"}
    zip_path.write_bytes(make_zip(entries).getvalue())

    packages.install(zip_path, {"BESPOK3D_KLIPPER": str(klipper_cfg_dir)})

    assert (klipper_cfg_dir / "cpu-temp.cfg").is_symlink()
    assert "/etc/init.d/S60klipper restart" in ran


class FakeServiceAdapter(FakeKlipperJinni):
    def capability_flags(self) -> set[str]:
        return {"managed-service"}

    def render_service_script(self, service: dict, paths: dict[str, str]) -> str:
        return f"#gen {service['name']} {service['command']}"


def test_managed_service_generates_and_wires_script(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    fake_adapter = FakeServiceAdapter()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: fake_adapter)
    ran: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)  # type: ignore[arg-type]
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    b3d = tmp_path / "b3d"
    service = {"name": "worker", "command": "/bin/worker", "autostart": True}
    manifest = minimal_manifest(extra={"install": {"service": [service]}})
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    packages.install(zip_path, {"BESPOK3D": str(b3d)})

    generated = tmp_path / "test-plugin" / "etc" / "init.d" / "s65worker"
    autostart = b3d / "etc" / "init.d" / "autostart" / "s65worker"
    assert generated.read_text() == "#gen worker /bin/worker"
    assert autostart.is_symlink()
    assert f"{autostart} restart" in ran


def test_managed_service_refused_without_capability(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)

    class NoServiceAdapter(FakeKlipperJinni):
        def capability_flags(self) -> set[str]:
            return set()

    no_service = NoServiceAdapter()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: no_service)
    manifest = minimal_manifest(
        extra={"install": {"service": [{"name": "worker", "command": "/bin/worker"}]}}
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    _plugin_id, log = packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3d")})

    service_phase = [phase for phase in log if phase["id"] == "services"][0]
    assert service_phase["ok"] is False
    assert "not supported" in service_phase["items"][0]["label"]


def test_patch_failure_shows_actual_context(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    target = tmp_path / "target.py"
    target.write_bytes(b"line one\r\nline two\r\nline three\r\n")
    patch_content = (
        "--- a/target.py\n+++ b/target.py\n"
        "@@ -1,3 +1,4 @@\n"
        "-wrong context\n"
        " line two\n"
        " line three\n"
        "+new line\n"
    )
    manifest_data = {
        "name": "diag-plugin",
        "version": "0.1.0",
        "install": {
            "dirs": [],
            "symlinks": [],
            "patches": [{"file": str(target), "patch": "files/target.patch"}],
        },
        "files": [],
    }
    zip_path = tmp_path / "diag-plugin.b3"
    entries: dict[str, bytes | str] = {
        "manifest.json": json.dumps(manifest_data),
        "files/target.patch": patch_content,
    }
    zip_path.write_bytes(make_zip(entries).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    patches_phase = next(phase for phase in log if phase["id"] == "patches")
    assert not patches_phase["ok"]
    failing_item = patches_phase["items"][0]
    assert "actual file" in failing_item["output"]
    assert "line one" in failing_item["output"]
    assert "CRLF stripped" in failing_item["output"]


def test_patch_crlf_target_succeeds(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    target = tmp_path / "target.py"
    target.write_bytes(b"line one\r\nline two\r\nline three\r\n")
    patch_content = (
        "--- a/target.py\n+++ b/target.py\n"
        "@@ -1,3 +1,4 @@\n"
        " line one\n"
        " line two\n"
        " line three\n"
        "+new line\n"
    )
    manifest_data = {
        "name": "crlf-plugin",
        "version": "0.1.0",
        "install": {
            "dirs": [],
            "symlinks": [],
            "patches": [{"file": str(target), "patch": "files/target.patch"}],
        },
        "files": [],
    }
    zip_path = tmp_path / "crlf-plugin.b3"
    entries: dict[str, bytes | str] = {
        "manifest.json": json.dumps(manifest_data),
        "files/target.patch": patch_content,
    }
    zip_path.write_bytes(make_zip(entries).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    patches_phase = next(phase for phase in log if phase["id"] == "patches")
    assert patches_phase["ok"]
    patched = target.read_text()
    assert "new line" in patched
    assert "\r" not in patched
    orig = tmp_path / "crlf-plugin" / "patches_orig" / "target.py"
    assert orig.exists()
    assert orig.read_bytes() == b"line one\r\nline two\r\nline three\r\n"


def test_uninstall_restores_original_from_orig_dir(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    target = tmp_path / "target.py"
    original_content = b"line one\nline two\nline three\n"
    target.write_bytes(original_content)
    patch_content = (
        "--- a/target.py\n+++ b/target.py\n"
        "@@ -1,3 +1,4 @@\n"
        " line one\n"
        " line two\n"
        " line three\n"
        "+new line\n"
    )
    manifest_data = {
        "name": "restore-plugin",
        "version": "0.1.0",
        "install": {
            "dirs": [],
            "symlinks": [],
            "patches": [{"file": str(target), "patch": "files/target.patch"}],
        },
        "files": [],
    }
    zip_path = tmp_path / "restore-plugin.b3"
    entries: dict[str, bytes | str] = {
        "manifest.json": json.dumps(manifest_data),
        "files/target.patch": patch_content,
    }
    zip_path.write_bytes(make_zip(entries).getvalue())

    packages.install(zip_path, {})
    assert "new line" in target.read_text()

    packages.uninstall("restore-plugin", {})
    assert target.read_bytes() == original_content


def test_uninstall_runs_stop_commands(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    ran: list[object] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    manifest = {
        "name": "stop-plugin",
        "version": "0.1.0",
        "install": {"dirs": [], "symlinks": [], "patches": []},
        "stop": ["echo bye"],
        "files": [],
    }
    zip_path = tmp_path / "stop-plugin.b3"
    zip_path.write_bytes(make_zip({"manifest.json": json.dumps(manifest)}).getvalue())
    packages.install(zip_path, {})
    ran.clear()
    packages.uninstall("stop-plugin", {})
    assert "echo bye" in ran


def test_uninstall_runs_declared_restart_hooks(tmp_path: Path, monkeypatch: MP) -> None:
    """A plugin that restarts Klipper on install must restart it on uninstall too, so the removed
    config/extra actually leaves the running service (regression: uninstall skipped the restart)."""
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    ran: list[object] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    klipper_cfg_dir = tmp_path / "config" / "bespok3d" / "klipper"
    klipper_cfg_dir.mkdir(parents=True)
    src_rel = "files/cfg/klipper/demo.cfg"
    manifest = minimal_manifest(
        extra={
            "install": {
                "place": [{"class": "klipper-config", "src": src_rel}],
                "restart": ["klipper"],
            },
            "files": [{"path": src_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest, src_rel: "[demo]"}).getvalue())
    packages.install(zip_path, {"BESPOK3D_KLIPPER": str(klipper_cfg_dir)})

    ran.clear()
    packages.uninstall("test-plugin", {"BESPOK3D_KLIPPER": str(klipper_cfg_dir)})

    assert not (klipper_cfg_dir / "demo.cfg").is_symlink()
    assert "/etc/init.d/S60klipper restart" in ran


def _install_restart_manifest(plugin_dir: Path, name: str, provides: list, depends: list) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "provides": provides,
        "depends": depends,
        "install": {"dirs": [], "symlinks": [], "patches": [], "restart": ["klipper"]},
        "files": [],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))


def test_cascade_uninstall_restarts_klipper_once(tmp_path: Path, monkeypatch: MP) -> None:
    """A cascade uninstall (target + dependents both restart Klipper) bounces Klipper exactly once,
    after everything is removed: the deferred restarts are collected up front and deduped."""
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    ran: list[object] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    _install_restart_manifest(tmp_path / "core", "core", provides=["core-svc"], depends=[])
    _install_restart_manifest(tmp_path / "leaf", "leaf", provides=[], depends=["core-svc"])

    removed = packages.uninstall("core", {}, cascade=True)

    assert set(removed) == {"core", "leaf"}
    assert not (tmp_path / "core").exists()
    assert not (tmp_path / "leaf").exists()
    assert ran.count("/etc/init.d/S60klipper restart") == 1


def test_teardown_restarts_core_services_once(tmp_path: Path, monkeypatch: MP) -> None:
    """A full teardown removes every plugin then bounces Klipper exactly once, after everything is
    gone (regression: teardown uninstalled per plugin, so it restarted Klipper/Moonraker and waited
    on their health once per plugin, a restart storm that read like an uninstall loop)."""
    import subprocess as sp

    plugin_root = tmp_path / "usr/local/plugins"
    plugin_root.mkdir(parents=True)
    ran: list[object] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeResult:
        ran.append(cmd)
        return FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)
    _install_restart_manifest(plugin_root / "alpha", "alpha", provides=[], depends=[])
    _install_restart_manifest(plugin_root / "beta", "beta", provides=[], depends=[])

    packages.teardown({"BESPOK3D": str(tmp_path)})

    assert not (plugin_root / "alpha").exists()
    assert not (plugin_root / "beta").exists()
    assert ran.count("/etc/init.d/S60klipper restart") == 1


def make_installed_plugin(  # noqa: PLR0913
    plugin_root: Path,
    plugin_id: str,
    provides: list[str] | None = None,
    depends: list[str] | None = None,
    symlinks: list[dict] | None = None,
    start: list[str] | None = None,
) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "name": plugin_id,
        "version": "0.1.0",
        "provides": provides or [],
        "depends": depends or [],
        "install": {
            "dirs": [],
            "symlinks": symlinks or [],
            "patches": [],
            "start": start or [],
        },
        "files": [],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def test_recover_returns_empty_when_no_plugins(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    assert packages.recover({}) == []


def test_recover_reapplies_symlinks(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    link_dst = tmp_path / "link.py"
    src_file = tmp_path / "alpha" / "files" / "mod.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("# mod")
    make_installed_plugin(
        tmp_path,
        "alpha",
        symlinks=[{"from": "files/mod.py", "to": str(link_dst)}],
    )

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(sp, "run", lambda *_a, **_kw: FakeResult())

    results = packages.recover({})

    assert len(results) == 1
    assert results[0]["plugin_id"] == "alpha"
    assert results[0]["ok"] is True
    assert link_dst.is_symlink()


def test_recover_skips_deactivated_plugins(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(tmp_path, "sleeping")
    (tmp_path / "sleeping" / "deactivated.json").write_text('{"reason": "test"}')

    results = packages.recover({})
    assert results == []


def test_recover_skips_dependent_when_provider_fails(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(tmp_path, "base-plugin", provides=["base-service"], start=["false"])
    make_installed_plugin(tmp_path, "needs-base", depends=["base-service"])

    class FakeOkBytes:
        returncode = 0
        stdout = b""
        stderr = b""

    class FakeFailBytes:
        returncode = 1
        stdout = b""
        stderr = b"fail"

    def fake_run(cmd: object, **kw: object) -> FakeOkBytes | FakeFailBytes:
        if isinstance(cmd, str) and "false" in cmd:
            return FakeFailBytes()
        return FakeOkBytes()

    monkeypatch.setattr(sp, "run", fake_run)

    results = packages.recover({})

    base_result = next(result for result in results if result["plugin_id"] == "base-plugin")
    needs_result = next(result for result in results if result["plugin_id"] == "needs-base")
    assert base_result["ok"] is False
    assert needs_result["skipped"] is True
    assert "dependency not satisfied" in needs_result["reason"]


def test_recover_deactivates_failed_plugin(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(tmp_path, "bad-plugin", start=["false"])

    class FakeOkBytes:
        returncode = 0
        stdout = b""
        stderr = b""

    class FakeFailBytes:
        returncode = 1
        stdout = b""
        stderr = b"fail"

    def fake_run(cmd: object, **kw: object) -> FakeOkBytes | FakeFailBytes:
        if isinstance(cmd, str) and "false" in cmd:
            return FakeFailBytes()
        return FakeOkBytes()

    monkeypatch.setattr(sp, "run", fake_run)

    results = packages.recover({})

    assert results[0]["plugin_id"] == "bad-plugin"
    assert results[0]["ok"] is False
    assert (tmp_path / "bad-plugin" / "deactivated.json").exists()
    assert (tmp_path / "bad-plugin" / "recovery_failure.json").exists()


def test_recover_clears_patches_orig_before_reapplying(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = make_installed_plugin(tmp_path, "patchy")
    stale_orig = plugin_dir / "patches_orig"
    stale_orig.mkdir()
    stale_file = stale_orig / "stale.py"
    stale_file.write_text("old backup")

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(sp, "run", lambda *_a, **_kw: FakeResult())

    packages.recover({})

    assert not stale_file.exists()


def test_install_returns_structured_log(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    target_dir = tmp_path / "somedir"
    src_rel = "files/mod.py"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [str(target_dir)],
                "symlinks": [{"from": src_rel, "to": str(tmp_path / "mod.py")}],
                "patches": [],
                "start": [],
            },
            "files": [{"path": src_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest, src_rel: "# mod"}).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    assert isinstance(log, list)
    assert len(log) > 0
    phase_ids = [phase["id"] for phase in log]
    assert "extract" in phase_ids
    assert "dirs" in phase_ids
    assert "symlinks" in phase_ids
    for phase in log:
        assert {"id", "label", "ok", "items"} <= phase.keys()
        for item in phase["items"]:
            assert {"label", "ok", "output"} <= item.keys()


def test_install_renders_template_to_plugin_local_path(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    template_rel = "files/webcam.conf.tmpl"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [],
                "patches": [],
                "templates": [{"from": template_rel, "to": "files/webcam.conf"}],
            },
            "files": [{"path": template_rel, "sha256": "", "mode": "644"}],
        }
    )
    template_body = "[webcam $WEBCAM_NAME]\nservice: webrtc-camerastreamer\n"
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, template_rel: template_body}).getvalue()
    )

    packages.install(
        zip_path,
        {"WEBCAM_NAME": "Toolhead"},
        user_vars={"WEBCAM_NAME": "Toolhead"},
    )

    rendered = tmp_path / "test-plugin" / "files" / "webcam.conf"
    assert rendered.read_text() == "[webcam Toolhead]\nservice: webrtc-camerastreamer\n"


def test_install_template_rejects_absolute_target(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    template_rel = "files/x.tmpl"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [],
                "patches": [],
                "templates": [{"from": template_rel, "to": "/etc/passwd"}],
            },
            "files": [{"path": template_rel, "sha256": "", "mode": "644"}],
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest, template_rel: "hi"}).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    templates_phase = next(phase for phase in log if phase["id"] == "templates")
    assert templates_phase["ok"] is False


def test_install_renders_template_before_symlink_so_symlink_target_exists(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    template_rel = "files/cfg.tmpl"
    dst = tmp_path / "linked.conf"
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "templates": [{"from": template_rel, "to": "files/cfg.conf"}],
                "symlinks": [{"from": "files/cfg.conf", "to": str(dst)}],
                "patches": [],
            },
            "files": [{"path": template_rel, "sha256": "", "mode": "644"}],
        }
    )
    template_body = "value = $V\n"
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(
        make_zip({"manifest.json": manifest, template_rel: template_body}).getvalue()
    )

    packages.install(zip_path, {"V": "ok"}, user_vars={"V": "ok"})

    assert dst.is_symlink()
    assert dst.read_text() == "value = ok\n"


def test_install_persists_user_vars(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    manifest = minimal_manifest()
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    packages.install(zip_path, {"FOO": "bar"}, user_vars={"FOO": "bar"})

    persisted = json.loads((tmp_path / "test-plugin" / "user_vars.json").read_text())
    assert persisted == {"FOO": "bar"}


def test_recover_defers_plugin_service_restarts(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(
        tmp_path, "cam",
        start=["echo gen-config", "/userdata/bespok3d/etc/init.d/autostart/s65cam restart"],
    )
    ran: list[str] = []

    class FakeOk:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeOk:
        ran.append(cmd)  # type: ignore[arg-type]
        return FakeOk()

    monkeypatch.setattr(sp, "run", fake_run)

    results = packages.recover({})

    # the plugin service restart is NOT run during the per-plugin phase
    cam_result = next(result for result in results if result["plugin_id"] == "cam")
    assert cam_result["ok"] is True
    # it runs once, batched at the end
    services = next(result for result in results if result["plugin_id"] == "(services)")
    assert services["ok"] is True
    assert ran.count("/userdata/bespok3d/etc/init.d/autostart/s65cam restart") == 1
    assert "echo gen-config" in ran


def test_recover_fails_plugin_missing_required_var(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = make_installed_plugin(tmp_path, "spoolman")
    manifest = json.loads((plugin_dir / "manifest.json").read_text())
    manifest["requires"] = {"variables": [{"name": "SPOOLMAN_SERVER", "required": True}]}
    manifest["install"]["start"] = ["sed 's/SPOOLMAN_SERVER/$SPOOLMAN_SERVER/g' a > b"]
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))

    results = packages.recover({})

    spoolman = next(result for result in results if result["plugin_id"] == "spoolman")
    assert spoolman["ok"] is False
    assert "SPOOLMAN_SERVER" in spoolman["reason"]
    # no services restart phase because nothing applied
    assert all(result["plugin_id"] != "(services)" for result in results)


def test_recover_defers_and_dedupes_service_restarts(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    import urllib.request as urlreq

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(
        tmp_path, "alpha",
        start=["echo alpha-cfg", "/etc/init.d/S60klipper restart", "/etc/init.d/S61moonraker restart"],  # noqa: E501
    )
    make_installed_plugin(
        tmp_path, "beta",
        start=["echo beta-cfg", "/etc/init.d/S60klipper restart"],
    )
    ran: list[str] = []

    class FakeOk:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd: object, **kw: object) -> FakeOk:
        ran.append(cmd)  # type: ignore[arg-type]
        return FakeOk()

    class FakeResponse:
        def read(self) -> bytes:
            return b"{}"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(urlreq, "urlopen", lambda *_a, **_kw: FakeResponse())

    results = packages.recover({})

    assert "echo alpha-cfg" in ran
    assert "echo beta-cfg" in ran
    assert ran.count("/etc/init.d/S60klipper restart") == 1
    assert ran.count("/etc/init.d/S61moonraker restart") == 1
    services = next(result for result in results if result["plugin_id"] == "(services)")
    assert services["ok"] is True


def test_recover_reports_failed_service_restart(
    tmp_path: Path, monkeypatch: MP, device_jinni: FakeKlipperJinni,
) -> None:
    import subprocess as sp

    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    make_installed_plugin(tmp_path, "alpha", start=["/etc/init.d/S60klipper restart"])

    class FakeOk:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(sp, "run", lambda *_a, **_kw: FakeOk())
    # The jinni reports the device unhealthy after the restart (klipper did not come back); the
    # daemon's safety net acts on that verdict, it never probes the device itself.
    monkeypatch.setattr(device_jinni, "health", lambda: DeviceHealth(services={
        "klipper": ServiceHealth(ready=False, detail="down"),
        "moonraker": ServiceHealth(ready=False, detail="down"),
    }))

    results = packages.recover({})

    alpha = next(result for result in results if result["plugin_id"] == "alpha")
    services = next(result for result in results if result["plugin_id"] == "(services)")
    assert alpha["ok"] is True
    assert services["ok"] is False
    # Nothing was attributable, so the catch-all reports honestly instead of leaving the user blind.
    assert "could not auto-fix" in services["reason"]


def test_restart_phase_waits_for_moonraker_when_restarted(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    import subprocess as sp
    import urllib.request as urlreq
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)

    class FakeOk:
        returncode = 0
        stdout = b""
        stderr = b""

    # Stub only the external boundary: the restart subprocess and the Moonraker HTTP probe.
    monkeypatch.setattr(sp, "run", lambda *_a, **_kw: FakeOk())
    monkeypatch.setattr(urlreq, "urlopen", lambda *_a, **_kw: _HealthyServerInfo())
    # A real core-service restart is an init.d action: it is deferred and run (with the health wait)
    # through the restart batch, not inline in the start phase.
    manifest = minimal_manifest(
        extra={
            "install": {
                "dirs": [],
                "symlinks": [],
                "patches": [],
                "start": ["/etc/init.d/S61moonraker restart"],
            }
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    _plugin_id, log = packages.install(zip_path, {})

    restart_phase = next(phase for phase in log if phase["id"] == "restart")
    assert restart_phase["ok"] is True
    assert any("moonraker" in item["label"] for item in restart_phase["items"])


def test_start_phase_skips_the_health_check_when_no_service_restarted(
    tmp_path: Path, monkeypatch: MP, device_jinni: FakeKlipperJinni,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    health_calls: list[bool] = []
    monkeypatch.setattr(device_jinni, "health", lambda: health_calls.append(True))
    manifest = minimal_manifest(
        extra={
            "install": {"dirs": [], "symlinks": [], "patches": [], "start": ["echo hello"]}
        }
    )
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    packages.install(zip_path, {})

    assert not health_calls


def test_validate_user_vars_accepts_valid_values() -> None:
    packages.validate_user_vars({"NAME": "Toolhead"})
    packages.validate_user_vars({"SERVER": "192.168.1.50:8000"})
    packages.validate_user_vars({"FILE": "/usr/local/bin/script.sh"})
    packages.validate_user_vars({"TAG": "opt_a@v1.0"})


def test_validate_user_vars_accepts_comma_separated_list() -> None:
    """List-valued config needs commas (regression: moonraker-notify NOTIFY_EVENTS install)."""
    packages.validate_user_vars({"NOTIFY_EVENTS": "complete,error,cancelled"})


def test_validate_user_vars_rejects_disallowed_chars() -> None:
    # Commas are allowed, but brace expansion (the comma's only shell power) needs braces, which
    # stay blocked, along with the other shell metacharacters.
    for bad in ["val<ue>", "cmd;inject", "line1\nline2", "$VAR", "{a,b}", "a|b", "x&y"]:
        with pytest.raises(ValueError, match="allows only"):
            packages.validate_user_vars({"KEY": bad})


def test_deactivate_all_writes_marker_and_removes_include_lines(
    tmp_path: Path, device_jinni: FakeKlipperJinni,
) -> None:
    plugin_dir = tmp_path / "usr" / "local" / "plugins" / "dummy"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"name": "dummy", "install": {"symlinks": [], "patches": []}})
    )
    printer_cfg = tmp_path / "printer.cfg"
    moonraker_cfg = tmp_path / "moonraker.cfg"
    printer_cfg.write_text("[include bespok3d/klipper/main.cfg]\n[printer]\n")
    moonraker_cfg.write_text("[include bespok3d/moonraker/main.cfg]\n[server]\n")
    # The jinni edits the printer's own config from its OWN paths (ADR-0037); point them at the tmp.
    device_jinni.paths_override = {"PRINTER_CFG": str(printer_cfg), "MOONRAKER_CFG": str(moonraker_cfg)}  # noqa: E501

    packages.deactivate_all({"BESPOK3D": str(tmp_path)})

    assert (tmp_path / "etc" / "deactivated").exists()
    assert "bespok3d/klipper" not in printer_cfg.read_text()
    assert "bespok3d/moonraker" not in moonraker_cfg.read_text()
    assert "[printer]" in printer_cfg.read_text()


def test_teardown_removes_plugin_dirs_and_include_lines(
    tmp_path: Path, device_jinni: FakeKlipperJinni,
) -> None:
    plugin_root = tmp_path / "usr" / "local" / "plugins"
    plugin_dir = plugin_root / "widget"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"name": "widget", "install": {"symlinks": [], "patches": []}})
    )
    printer_cfg = tmp_path / "printer.cfg"
    moonraker_cfg = tmp_path / "moonraker.cfg"
    printer_cfg.write_text("[include bespok3d/klipper/main.cfg]\n[printer]\n")
    moonraker_cfg.write_text("[include bespok3d/moonraker/main.cfg]\n[server]\n")
    device_jinni.paths_override = {"PRINTER_CFG": str(printer_cfg), "MOONRAKER_CFG": str(moonraker_cfg)}  # noqa: E501

    packages.teardown({"BESPOK3D": str(tmp_path)})

    assert not plugin_dir.exists()
    assert "bespok3d/klipper" not in printer_cfg.read_text()
    assert "bespok3d/moonraker" not in moonraker_cfg.read_text()


def test_deactivate_blocked_during_print(monkeypatch: MP, device_jinni: FakeKlipperJinni) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    with pytest.raises(packages.BlockedActionError):
        packages.deactivate_all({"BESPOK3D": "/x"})


def test_teardown_blocked_during_print(monkeypatch: MP, device_jinni: FakeKlipperJinni) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "paused"))
    with pytest.raises(packages.BlockedActionError):
        packages.teardown({"BESPOK3D": "/x"})


def test_recover_blocked_during_print(monkeypatch: MP, device_jinni: FakeKlipperJinni) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    with pytest.raises(packages.BlockedActionError):
        packages.recover({"BESPOK3D": "/x"})


def write_plugin(
    root: Path,
    name: str,
    *,
    provides: list[str] | None = None,
    depends: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "provides": provides or [],
        "depends": depends or [],
        "conflicts": conflicts or [],
        "install": {"dirs": [], "symlinks": [], "patches": []},
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def test_installed_dependents_reports_consumer(tmp_path: Path) -> None:
    write_plugin(tmp_path, "provider", provides=["svc"])
    write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    assert dependencies.installed_dependents(tmp_path, "provider") == ["consumer"]
    assert dependencies.installed_dependents(tmp_path, "consumer") == []


def test_installed_dependents_reads_service_model(tmp_path: Path) -> None:
    manifests = {
        "provider": {"provides": [{"service": "svc"}], "require": []},
        "consumer": {"provides": [], "require": [{"service": "svc", "cardinality": "one"}]},
    }
    for name, fields in manifests.items():
        plugin_dir = tmp_path / name
        plugin_dir.mkdir()
        manifest = {"name": name, "version": "0.1.0", "install": {}, **fields}
        (plugin_dir / "manifest.json").write_text(json.dumps(manifest))

    assert dependencies.installed_dependents(tmp_path, "provider") == ["consumer"]


def test_uninstall_refuses_when_a_dependent_is_installed(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    write_plugin(tmp_path, "provider", provides=["svc"])
    write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    with pytest.raises(packages.DependentsError) as excinfo:
        packages.uninstall("provider", {})
    assert excinfo.value.dependents == ["consumer"]
    assert (tmp_path / "provider").exists()


def test_uninstall_cascade_removes_dependents_then_target(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    write_plugin(tmp_path, "provider", provides=["svc"])
    write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    removed = packages.uninstall("provider", {}, cascade=True)

    assert removed == ["consumer", "provider"]
    assert not (tmp_path / "provider").exists()
    assert not (tmp_path / "consumer").exists()


def test_uninstall_without_dependents_returns_target(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    write_plugin(tmp_path, "lonely", provides=["svc"])

    assert packages.uninstall("lonely", {}) == ["lonely"]
    assert not (tmp_path / "lonely").exists()


def test_install_refuses_a_conflicting_package(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    write_plugin(tmp_path, "installed-one", provides=["svc-a"])
    zip_path = tmp_path / "new-one.b3"
    manifest = minimal_manifest("new-one", {"conflicts": ["installed-one"]})
    zip_path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())

    with pytest.raises(packages.ConflictError) as excinfo:
        packages.install(zip_path, {})
    assert excinfo.value.conflicts == ["installed-one"]
    assert not (tmp_path / "new-one").exists()


def test_install_conflict_is_detected_in_reverse(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    write_plugin(tmp_path, "installed-two", conflicts=["new-two"])
    zip_path = tmp_path / "new-two.b3"
    zip_path.write_bytes(make_zip({"manifest.json": minimal_manifest("new-two")}).getvalue())

    with pytest.raises(packages.ConflictError) as excinfo:
        packages.install(zip_path, {})
    assert excinfo.value.conflicts == ["installed-two"]


class _FakeRunOk:
    returncode = 0
    stdout = b""
    stderr = b""


class _FakeEmptyJsonResponse:
    def read(self) -> bytes:
        return b"{}"

    def __enter__(self) -> "_FakeEmptyJsonResponse":
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def make_package_file(
    tmp_path: Path, name: str, start: list[str] | None = None, version: str = "0.2.0",
) -> Path:
    manifest = json.dumps({
        "name": name,
        "version": version,
        "install": {"dirs": [], "symlinks": [], "patches": [], "start": start or []},
        "files": [],
    })
    path = tmp_path / f"{name}.b3"
    path.write_bytes(make_zip({"manifest.json": manifest}).getvalue())
    return path


def test_update_batch_empty_returns_empty(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    assert packages.update_batch({}, [], {}) == []


def test_update_batch_defers_and_dedupes_restarts(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    import urllib.request as urlreq

    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    alpha = make_package_file(
        tmp_path, "alpha",
        start=["echo alpha-cfg", "/etc/init.d/S60klipper restart", "/etc/init.d/S61moonraker restart"],  # noqa: E501
    )
    beta = make_package_file(
        tmp_path, "beta",
        start=["echo beta-cfg", "/etc/init.d/S60klipper restart"],
    )
    ran: list[str] = []

    def fake_run(cmd: object, **_kw: object) -> _FakeRunOk:
        ran.append(cmd)  # type: ignore[arg-type]
        return _FakeRunOk()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(urlreq, "urlopen", lambda *_a, **_kw: _FakeEmptyJsonResponse())

    results = packages.update_batch({}, [alpha, beta], {})

    assert (plugin_root / "alpha" / "manifest.json").exists()
    assert (plugin_root / "beta" / "manifest.json").exists()
    assert "echo alpha-cfg" in ran
    assert "echo beta-cfg" in ran
    # each affected service restarts exactly once for the whole batch
    assert ran.count("/etc/init.d/S60klipper restart") == 1
    assert ran.count("/etc/init.d/S61moonraker restart") == 1
    services = next(result for result in results if result["plugin_id"] == "(services)")
    assert services["ok"] is True


def test_update_batch_applies_per_plugin_user_vars(tmp_path: Path, monkeypatch: MP) -> None:
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    package = make_package_file(tmp_path, "spoolman")

    packages.update_batch({}, [package], {"spoolman": {"SPOOLMAN_SERVER": "printer.local"}})

    saved = json.loads((plugin_root / "spoolman" / packages.USER_VARS_FILE).read_text())
    assert saved == {"SPOOLMAN_SERVER": "printer.local"}


def test_update_batch_refused_during_print(
    tmp_path: Path, monkeypatch: MP, device_jinni: FakeKlipperJinni,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    package = make_package_file(tmp_path, "alpha", start=["/etc/init.d/S60klipper restart"])

    with pytest.raises(packages.BlockedActionError):
        packages.update_batch({}, [package], {})


class _RecordingRun:
    """A subprocess.run double that records every command and reports success."""

    def __init__(self) -> None:
        self.commands: list[object] = []

    def __call__(self, cmd: object, **kw: object) -> object:
        self.commands.append(cmd)

        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return Result()

def test_venv_provisioned_from_requirements_presence(tmp_path: Path, monkeypatch: MP) -> None:
    import subprocess as sp
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    recorder = _RecordingRun()
    monkeypatch.setattr(sp, "run", recorder)
    bespok3d = tmp_path / "b3"
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": minimal_manifest("notifier", extra={"install": {}}),
        "requirements.txt": "humanize>=4.9.0",
        "files/wheels/humanize-4.15.0-py3-none-any.whl": b"wheel",
    }).getvalue())

    _plugin_id, log = packages.install(zip_path, {"BESPOK3D": str(bespok3d)})

    venv = str(bespok3d / "venv-plugins" / "notifier")
    lists = [cmd for cmd in recorder.commands if isinstance(cmd, list)]
    assert ["python3", "-m", "venv", venv] in lists
    assert any(cmd[:3] == [f"{venv}/bin/pip", "install", "--no-index"] for cmd in lists)
    assert "python" in [phase["id"] for phase in log]


def test_no_python_phase_without_a_requirements_file(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({"manifest.json": minimal_manifest("plain")}).getvalue())

    _plugin_id, log = packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3")})

    phase_ids = [phase["id"] for phase in log]
    assert "python" not in phase_ids
    assert "site_packages" not in phase_ids


def test_install_exposes_plugin_venv_var(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    bespok3d = tmp_path / "b3"
    manifest = minimal_manifest("venv-var", extra={"install": {
        "templates": [{"from": "files/cmd.tmpl", "to": "files/cmd.txt"}],
    }})
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest,
        "files/cmd.tmpl": "$PLUGIN_VENV/bin/python3",
    }).getvalue())

    packages.install(zip_path, {"BESPOK3D": str(bespok3d)})

    rendered = (tmp_path / "venv-var" / "files" / "cmd.txt").read_text()
    assert rendered == f"{bespok3d}/venv-plugins/venv-var/bin/python3"


def test_install_rejects_both_dep_files(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": minimal_manifest("both"),
        "requirements.txt": "a",
        "klipper_requirements.txt": "b",
    }).getvalue())

    with pytest.raises(ValueError, match="not both"):
        packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3")})


def test_install_auto_deactivates_plugin_that_breaks_a_service(
    tmp_path: Path, monkeypatch: MP, device_jinni: FakeKlipperJinni,
) -> None:
    """A FRESH install whose Moonraker component fails to import must auto-deactivate the culprit
    and leave the printer working, the same safety net as recover/OTA. The jinni reports Moonraker
    REACHABLE but with a FAILED COMPONENT (not a dead server), which the old reachability-only check
    missed; its verdict flips healthy once deactivation removes the broken cfg."""
    import subprocess as sp
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    moonraker_cfg = tmp_path / "config" / "bespok3d" / "moonraker"
    moonraker_cfg.mkdir(parents=True)
    cfg_link = moonraker_cfg / "notifier.cfg"

    class FakeOk:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(sp, "run", lambda *_a, **_kw: FakeOk())

    def health() -> DeviceHealth:
        # While the broken plugin's cfg is in place the jinni reports a failed Moonraker component;
        # once deactivation removes the cfg the device is healthy again.
        failed = ("notifier",) if cfg_link.exists() else ()
        return DeviceHealth(services={
            "klipper": ServiceHealth(ready=True, detail="ready"),
            "moonraker": ServiceHealth(ready=True, detail="up", failed_components=failed),
        })

    monkeypatch.setattr(device_jinni, "health", health)
    manifest = minimal_manifest("notifier-ish", extra={
        "install": {
            "place": [{"class": "moonraker-config", "src": "files/cfg/moonraker/notifier.cfg"}],
            "restart": ["moonraker"],
        },
        "files": [{"path": "files/cfg/moonraker/notifier.cfg", "sha256": "", "mode": "644"}],
    })
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest,
        "files/cfg/moonraker/notifier.cfg": "[notifier phone]\n",
    }).getvalue())

    _plugin_id, log = packages.install(
        zip_path, {"BESPOK3D": str(tmp_path / "b3"), "BESPOK3D_MOONRAKER": str(moonraker_cfg)},
    )

    assert (plugin_root / "notifier-ish" / "deactivated.json").exists()
    recovery = next(phase for phase in log if phase["id"] == "auto-recovery")
    assert recovery["ok"] is False  # the just-installed plugin was disabled to save the printer
    assert not cfg_link.is_symlink()  # its config was removed, so Moonraker recovered


def test_install_rejects_klipper_requirements_without_baked_packages(tmp_path: Path, monkeypatch: MP) -> None:  # noqa: E501
    """Declared-but-unbaked deps fail loudly at install (regression: moonraker-notify shipped
    klipper_requirements.txt but no files/site-packages, so apprise was never linked and Moonraker
    failed to import it at runtime)."""
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": minimal_manifest("notify", extra={"install": {}}),
        "klipper_requirements.txt": "apprise>=1.7.0",
    }).getvalue())

    with pytest.raises(ValueError, match="files/site-packages"):
        packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3")})


def test_install_rejects_requirements_without_baked_wheels(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": minimal_manifest("svc", extra={"install": {}}),
        "requirements.txt": "humanize>=4.9.0",
    }).getvalue())

    with pytest.raises(ValueError, match="files/wheels"):
        packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3")})


def test_uninstall_removes_plugin_venv(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = tmp_path / "notifier"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(minimal_manifest("notifier"))
    bespok3d = tmp_path / "b3"
    venv = bespok3d / "venv-plugins" / "notifier"
    venv.mkdir(parents=True)
    (venv / "marker").write_text("x")

    packages.uninstall("notifier", {"BESPOK3D": str(bespok3d)})

    assert not venv.exists()
    assert not plugin_dir.exists()


def _site_link_b3(zip_path: Path, plugin_name: str) -> None:
    manifest = minimal_manifest(plugin_name, extra={"install": {}})
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest,
        "klipper_requirements.txt": "humanize>=4.9.0",
        "files/site-packages/humanize/__init__.py": "def naturaldelta(seconds): return 'a while'",
        "files/site-packages/humanize-4.15.0.dist-info/METADATA": "Name: humanize",
    }).getvalue())


def test_site_link_created_for_baked_top_level(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    monkeypatch.setattr(python_deps, "_already_importable", lambda module: False)
    site_pkgs = tmp_path / "site-packages"
    zip_path = tmp_path / "p.b3"
    _site_link_b3(zip_path, "notifier")

    packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3"), "PYTHON_SITE_PACKAGES": str(site_pkgs)})  # noqa: E501

    link = site_pkgs / "humanize"
    assert link.is_symlink()
    assert (link / "__init__.py").exists()


def test_site_link_preserves_existing_base_package(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    monkeypatch.setattr(python_deps, "_already_importable", lambda module: True)
    site_pkgs = tmp_path / "site-packages"
    zip_path = tmp_path / "p.b3"
    _site_link_b3(zip_path, "notifier")

    _plugin_id, log = packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3"), "PYTHON_SITE_PACKAGES": str(site_pkgs)})  # noqa: E501

    assert not (site_pkgs / "humanize").exists()
    site_phase = next(phase for phase in log if phase["id"] == "site_packages")
    assert site_phase["ok"] is False


def test_site_link_conflict_refused_on_version_mismatch(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    monkeypatch.setattr(python_deps, "_already_importable", lambda module: False)
    site_pkgs = tmp_path / "site-packages"
    site_pkgs.mkdir()
    other = tmp_path / "other"
    (other / "files/site-packages/humanize").mkdir(parents=True)
    (other / "files/site-packages/humanize-1.0.0.dist-info").mkdir()
    (site_pkgs / "humanize").symlink_to(other / "files/site-packages/humanize")
    zip_path = tmp_path / "p.b3"
    _site_link_b3(zip_path, "notifier")

    _plugin_id, log = packages.install(zip_path, {"BESPOK3D": str(tmp_path / "b3"), "PYTHON_SITE_PACKAGES": str(site_pkgs)})  # noqa: E501

    assert (site_pkgs / "humanize").resolve() == (other / "files/site-packages/humanize").resolve()
    site_phase = next(phase for phase in log if phase["id"] == "site_packages")
    assert site_phase["ok"] is False


_EXTRA_REL = "files/klipper/klippy/extras/print_time_human.py"


def _arrange_extra_install(tmp_path: Path, monkeypatch: MP) -> dict:
    """An installable Klipper-extra-with-deps .b3 (klipper_requirements.txt + baked packages)."""
    import subprocess as sp
    import urllib.request as urlreq
    bespok3d = tmp_path / "data"
    plugin_root = bespok3d / "usr/local/plugins"
    plugin_root.mkdir(parents=True)
    site_pkgs = tmp_path / "site-packages"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(python_deps, "_already_importable", lambda module: False)
    # Stub the HTTP boundary healthy so the post-restart safety check sees a working printer.
    monkeypatch.setattr(urlreq, "urlopen", lambda *_a, **_kw: _HealthyServerInfo())
    monkeypatch.setattr(sp, "run", _RecordingRun())
    manifest = minimal_manifest("print-time-human", extra={
        "install": {"place": [{"class": "klipper-extra", "src": _EXTRA_REL}], "restart": ["klipper"]},  # noqa: E501
        "files": [{"path": _EXTRA_REL, "sha256": "", "mode": "644"}],
    })
    zip_path = tmp_path / "p.b3"
    zip_path.write_bytes(make_zip({
        "manifest.json": manifest,
        _EXTRA_REL: "import humanize\nload_config = lambda config: None",
        "klipper_requirements.txt": "humanize>=4.9.0",
        "files/site-packages/humanize/__init__.py": "def naturaldelta(seconds): return 'a while'",
        "files/site-packages/humanize-4.15.0.dist-info/METADATA": "Name: humanize",
    }).getvalue())
    extras_dir = tmp_path / "klipper_extras"
    install_vars = {
        "BESPOK3D": str(bespok3d), "KLIPPER_EXTRAS": str(extras_dir),
        "PYTHON_SITE_PACKAGES": str(site_pkgs),
        "PRINTER_CFG": str(tmp_path / "printer.cfg"), "MOONRAKER_CFG": str(tmp_path / "moonraker.conf"),  # noqa: E501
    }
    return {
        "zip": zip_path, "vars": install_vars, "plugin_dir": plugin_root / "print-time-human",
        "linked_extra": extras_dir / "print_time_human.py", "site_link": site_pkgs / "humanize",
    }


def test_klipper_extra_with_deps_lifecycle(tmp_path: Path, monkeypatch: MP) -> None:
    # ADR-0036 extras case: a plain Klipper extra plus a baked dep. Install symlinks the extra into
    # the Klipper extras dir AND the dep into the system site-packages (no pip on the printer).
    # Deactivate removes both symlinks; uninstall removes the whole plugin dir.
    setup = _arrange_extra_install(tmp_path, monkeypatch)

    packages.install(setup["zip"], setup["vars"])
    assert setup["linked_extra"].is_symlink()
    assert setup["site_link"].is_symlink()
    assert (setup["site_link"] / "__init__.py").exists()

    packages.deactivate_all(setup["vars"])
    assert not setup["linked_extra"].exists()
    assert not setup["site_link"].exists()

    packages.uninstall("print-time-human", setup["vars"])
    assert not setup["plugin_dir"].exists()
