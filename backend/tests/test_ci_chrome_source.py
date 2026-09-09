"""Only temporary apt fixtures; never inspect or modify the host's apt setup."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "ci_chrome", Path(__file__).parents[2] / "scripts/disable_ci_chrome_source.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
URI = module.URI


@pytest.mark.parametrize("format", ["list", "sources"])
def test_only_dedicated_matching_file_is_disabled(tmp_path, format, capsys):
    folder = tmp_path / "sources.list.d"
    folder.mkdir()
    path = folder / ("arbitrary-runner-name." + format)
    content = (
        f"# generated runner source\ndeb [arch=amd64 signed-by=/keys/google.gpg] {URI}/ stable main\n"
        if format == "list"
        else f"Types: deb\nURIs: {URI}/\nSuites: stable\nComponents: main\nSigned-By: /keys/google.gpg\n"
    )
    path.write_text(content)
    other = folder / "ubuntu.list"
    other.write_text("deb https://archive.ubuntu.com/ubuntu noble main\n")
    assert module.disable_sources(tmp_path) == [path]
    assert not path.exists()
    assert path.with_name(path.name + ".disabled").read_text() == content
    assert other.read_text() == "deb https://archive.ubuntu.com/ubuntu noble main\n"
    output = capsys.readouterr().out
    assert str(path) in output and URI in output
    assert module.disable_sources(tmp_path) == []


@pytest.mark.parametrize(
    "mixed",
    [
        f"deb {URI} stable main\ndeb https://archive.ubuntu.com/ubuntu noble main\n",
        f"Types: deb\nURIs: {URI} https://archive.ubuntu.com/ubuntu\nSuites: stable\nComponents: main\n",
        f"Types: deb\nURIs: {URI}\nSuites: stable\n\nTypes: deb\nURIs: https://archive.ubuntu.com/ubuntu\n",
    ],
)
def test_mixed_sources_fail_without_modifying_any_file(tmp_path, mixed):
    folder = tmp_path / "sources.list.d"
    folder.mkdir()
    first = folder / "a.list"
    first.write_text(f"deb {URI} stable main\n")
    path = folder / ("mixed.list" if mixed.startswith("deb") else "mixed.sources")
    path.write_text(mixed)
    with pytest.raises(ValueError, match="Cannot safely isolate"):
        module.disable_sources(tmp_path)
    assert path.read_text() == mixed and first.is_file()
    assert not list(folder.glob("*.disabled"))


def test_no_target_or_existing_backup_preserves_files(tmp_path):
    main = tmp_path / "sources.list"
    main.write_text(
        f"# deb {URI} stable main\ndeb https://archive.ubuntu.com/ubuntu noble main\n"
    )
    assert module.disable_sources(tmp_path) == []
    main.write_text(f"deb {URI} stable main\n")
    backup = tmp_path / "sources.list.disabled"
    backup.write_text("prior record")
    with pytest.raises(ValueError, match="Cannot safely isolate"):
        module.disable_sources(tmp_path)
    assert main.is_file() and backup.read_text() == "prior record"


def test_entrypoint_rejects_non_ci_before_host_access():
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts/disable_ci_chrome_source.py"),
        ],
        env={**os.environ, "GITHUB_ACTIONS": "false"},
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode != 0
        and "restricted to the ephemeral CI runner" in result.stderr
    )
