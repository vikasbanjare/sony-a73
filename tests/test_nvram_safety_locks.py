import json

import pytest

from a7iii.nvram import (
    BackupIntegrityError,
    FakeSenserBackend,
    NvramBackup,
    NvramService,
    TWEAKS,
    UnsafeWriteError,
    validate_write,
)
from a7iii.nvram.registry import ID_MODEL_CODE, ID_MODEL_NAME, ID_SERIAL_NUMBER, LANGUAGE_FIRST, LANGUAGE_LAST
from a7iii.nvram.service import VerificationError

CALIBRATION_LIKE = 0x00E80001  # arbitrary non-allowlisted id


def camera(serial=b"1234567\0"):
    props = {ID_MODEL_NAME: b"ILCE-7M3\0", ID_MODEL_CODE: b"\x01", ID_SERIAL_NUMBER: serial, CALIBRATION_LIKE: b"\xaa"}
    props.update({pid: b"\x02" for pid in range(LANGUAGE_FIRST, LANGUAGE_LAST + 1)})
    return FakeSenserBackend(props)


def test_non_allowlisted_writes_are_refused():
    with pytest.raises(UnsafeWriteError):
        validate_write(CALIBRATION_LIKE, b"\x01")
    with pytest.raises(UnsafeWriteError):
        validate_write(LANGUAGE_FIRST, b"\x07")  # allowlisted id, bad value
    validate_write(LANGUAGE_FIRST, b"\x01")


def test_unverified_tweaks_cannot_be_planned():
    svc = NvramService(camera())
    for key in ("rec_limit", "pal_ntsc_warning"):
        assert not TWEAKS[key].available
        with pytest.raises(UnsafeWriteError):
            svc.plan(key)


def test_dump_is_read_only_and_sealed(tmp_path):
    be = camera()
    backup = NvramService(be).dump()
    assert not any(entry[0] in ("write", "protect", "sync") for entry in be.log)
    assert backup.serial == "1234567" and backup.model == "ILCE-7M3"
    path = backup.save(tmp_path)
    assert NvramBackup.load(path).props == backup.props

    raw = json.loads(path.read_text())
    raw["props"][f"0x{LANGUAGE_FIRST:08x}"] = "01"
    path.write_text(json.dumps(raw))
    with pytest.raises(BackupIntegrityError):
        NvramBackup.load(path)


def test_dry_run_writes_nothing():
    be = camera()
    svc = NvramService(be)
    report = svc.apply(svc.plan("languages"), svc.dump(), dry_run=True)
    assert report.dry_run and not report.written
    assert all(be.props[p] == b"\x02" for p in TWEAKS["languages"].prop_ids)
    assert be.synced == 0


def test_apply_languages_end_to_end():
    be = camera()
    svc = NvramService(be)
    backup = svc.dump()
    report = svc.apply(svc.plan("languages"), backup, dry_run=False)
    assert len(report.written) == len(TWEAKS["languages"].prop_ids) == 35
    assert all(be.props[p] == b"\x01" for p in TWEAKS["languages"].prop_ids)
    assert be.protected and be.synced == 1
    assert be.props[CALIBRATION_LIKE] == b"\xaa"

    svc.restore(backup, dry_run=False)
    assert all(be.props[p] == b"\x02" for p in TWEAKS["languages"].prop_ids)


def test_backup_from_other_body_is_rejected():
    other = NvramService(camera(serial=b"7654321\0")).dump()
    svc = NvramService(camera())
    with pytest.raises(UnsafeWriteError, match="backup is for"):
        svc.apply(svc.plan("languages"), other, dry_run=False)


def test_backup_must_contain_written_props():
    svc = NvramService(camera())
    partial = svc.dump(prop_ids=[])
    with pytest.raises(UnsafeWriteError, match="does not contain"):
        svc.apply(svc.plan("languages"), partial, dry_run=False)


def test_failed_readback_reprotects_and_skips_sync():
    be = camera()
    original_write = be.write_backup
    be.write_backup = lambda pid, val: original_write(pid, b"\x02")  # silently ignores the new value
    svc = NvramService(be)
    with pytest.raises(VerificationError):
        svc.apply(svc.plan("languages"), svc.dump(), dry_run=False)
    assert be.protected and be.synced == 0
