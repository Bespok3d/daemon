from pathlib import Path

from core import python_env


def test_plugin_venv_path_is_under_bespok3d() -> None:
    venv = python_env.plugin_venv_path("/userdata/bespok3d", "notifier")
    assert venv == Path("/userdata/bespok3d/venv-plugins/notifier")


def test_venv_create_command() -> None:
    assert python_env.venv_create_command(Path("/v")) == ["python3", "-m", "venv", "/v"]


def test_plugin_wheels_dir() -> None:
    assert python_env.plugin_wheels_dir(Path("/p")) == Path("/p/files/wheels")


def test_requirements_install_is_offline_no_resolver() -> None:
    # The baked wheels are the full closure, so install them directly with --no-deps and no
    # --find-links/-r: the offline resolver never runs, so it cannot backtrack and fail.
    wheels = [
        Path("/p/files/wheels/a-1.0-py3-none-any.whl"),
        Path("/p/files/wheels/b-2.0-py3-none-any.whl"),
    ]
    command = python_env.requirements_install_command(Path("/v"), wheels)
    assert command == [
        "/v/bin/pip", "install", "--no-index", "--no-deps",
        "/p/files/wheels/a-1.0-py3-none-any.whl",
        "/p/files/wheels/b-2.0-py3-none-any.whl",
    ]


def test_requirements_install_with_no_wheels_installs_nothing() -> None:
    command = python_env.requirements_install_command(Path("/v"), [])
    assert command == ["/v/bin/pip", "install", "--no-index", "--no-deps"]


def test_import_name_strips_py_suffix() -> None:
    assert python_env.import_name("humanize.py") == "humanize"
    assert python_env.import_name("humanize") == "humanize"


def test_baked_site_packages_dir() -> None:
    assert python_env.baked_site_packages_dir(Path("/p")) == Path("/p/files/site-packages")


def test_system_site_packages_from_vars() -> None:
    declared = {"PYTHON_SITE_PACKAGES": "/usr/lib/py"}
    assert python_env.system_site_packages(declared) == Path("/usr/lib/py")
    assert python_env.system_site_packages({}) is None
