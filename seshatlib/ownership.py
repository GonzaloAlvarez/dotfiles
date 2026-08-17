import os
import stat
from dataclasses import dataclass
from enum import Enum

from .state import sha256_file


class Status(Enum):
    ABSENT = "absent"
    CURRENT = "current"
    OUTDATED = "outdated"
    MODIFIED = "modified"
    MISSING = "missing"
    ADOPTABLE = "adoptable"
    CONFLICT_UNMANAGED = "conflict-unmanaged"
    CONFLICT_OTHER_OWNER = "conflict-other-owner"


@dataclass
class FsInfo:
    kind: str
    sha: str = None
    mode: int = None
    link_target: str = None


def probe(path):
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return FsInfo(kind="absent")
    if stat.S_ISLNK(st.st_mode):
        return FsInfo(kind="link", link_target=os.readlink(path))
    if stat.S_ISDIR(st.st_mode):
        return FsInfo(kind="dir", mode=st.st_mode & 0o7777)
    if stat.S_ISREG(st.st_mode):
        return FsInfo(kind="file", sha=sha256_file(path), mode=st.st_mode & 0o7777)
    return FsInfo(kind="special")


def classify_whole_file(bundle_id, desired_sha, desired_mode, record, fs):
    if record is not None and record.get("owner") != bundle_id:
        return Status.CONFLICT_OTHER_OWNER
    if record is None:
        if fs.kind == "absent":
            return Status.ABSENT
        if fs.kind == "file" and fs.sha == desired_sha:
            return Status.ADOPTABLE
        return Status.CONFLICT_UNMANAGED
    if fs.kind == "absent":
        return Status.MISSING
    if fs.kind != "file":
        return Status.MODIFIED
    if fs.sha == record.get("installed_sha256"):
        if fs.sha == desired_sha and (desired_mode is None or fs.mode == desired_mode):
            return Status.CURRENT
        return Status.OUTDATED
    if fs.sha == desired_sha:
        return Status.ADOPTABLE
    return Status.MODIFIED


def classify_link(bundle_id, desired_target, record, fs):
    if record is not None and record.get("owner") != bundle_id:
        return Status.CONFLICT_OTHER_OWNER
    if record is None:
        if fs.kind == "absent":
            return Status.ABSENT
        if fs.kind == "link" and fs.link_target == desired_target:
            return Status.ADOPTABLE
        return Status.CONFLICT_UNMANAGED
    if fs.kind == "absent":
        return Status.MISSING
    if fs.kind != "link":
        return Status.MODIFIED
    if fs.link_target == record.get("link_target"):
        if fs.link_target == desired_target:
            return Status.CURRENT
        return Status.OUTDATED
    if fs.link_target == desired_target:
        return Status.ADOPTABLE
    return Status.MODIFIED


def classify_json_key(bundle_id, desired_hash, krec, present, current_hash):
    if krec is not None and krec.get("owner") != bundle_id:
        return Status.CONFLICT_OTHER_OWNER
    if krec is None:
        if not present:
            return Status.ABSENT
        if current_hash == desired_hash:
            return Status.ADOPTABLE
        return Status.CONFLICT_UNMANAGED
    if not present:
        return Status.MISSING
    if current_hash == krec.get("installed_sha256"):
        if current_hash == desired_hash:
            return Status.CURRENT
        return Status.OUTDATED
    if current_hash == desired_hash:
        return Status.ADOPTABLE
    return Status.MODIFIED


def file_drift(record, fs):
    if fs.kind == "absent":
        return "missing"
    if fs.kind != "file":
        return "modified"
    if fs.sha != record.get("installed_sha256"):
        return "modified"
    rec_mode = record.get("mode")
    if rec_mode is not None and fs.mode != int(rec_mode, 8):
        return "modified"
    return None


def link_drift(record, fs):
    if fs.kind == "absent":
        return "missing"
    if fs.kind != "link":
        return "modified"
    if fs.link_target != record.get("link_target"):
        return "modified"
    return None


def json_key_drift(krec, present, current_hash):
    if not present:
        return "missing"
    if current_hash != krec.get("installed_sha256"):
        return "modified"
    return None
