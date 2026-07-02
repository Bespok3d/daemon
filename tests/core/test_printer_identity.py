from pathlib import Path
from uuid import UUID

import pytest

from core import printer_identity


@pytest.fixture(autouse=True)
def identity_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        printer_identity, "IDENTITY_PATH", tmp_path / "etc/daemon/printer_uuid"
    )


def test_first_boot_mints_a_uuid_and_persists_it() -> None:
    minted = printer_identity.ensure_printer_uuid()
    UUID(minted)
    assert printer_identity.IDENTITY_PATH.read_text() == minted


def test_ensure_is_idempotent_across_restarts() -> None:
    first_boot = printer_identity.ensure_printer_uuid()
    second_boot = printer_identity.ensure_printer_uuid()
    assert second_boot == first_boot


def test_an_existing_identity_is_never_regenerated() -> None:
    printer_identity.IDENTITY_PATH.parent.mkdir(parents=True)
    printer_identity.IDENTITY_PATH.write_text("11111111-2222-3333-4444-555555555555\n")
    assert printer_identity.ensure_printer_uuid() == "11111111-2222-3333-4444-555555555555"


def test_stored_is_none_before_first_boot() -> None:
    assert printer_identity.stored_printer_uuid() is None


def test_an_empty_identity_file_reads_as_absent_and_is_re_minted() -> None:
    printer_identity.IDENTITY_PATH.parent.mkdir(parents=True)
    printer_identity.IDENTITY_PATH.write_text("")
    assert printer_identity.stored_printer_uuid() is None
    UUID(printer_identity.ensure_printer_uuid())
