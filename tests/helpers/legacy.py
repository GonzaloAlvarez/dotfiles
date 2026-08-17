import os
from pathlib import Path


def legacy_combine(src_dir):
    src_dir = Path(src_dir)
    out = b""
    for name in sorted(os.listdir(src_dir)):
        p = src_dir / name
        if p.is_file():
            out += p.read_bytes() + b"\n"
    return out


def legacy_copy(src):
    return Path(src).read_bytes()


def legacy_json_merge(dest_doc, src_doc):
    merged = dict(dest_doc)
    merged.update(src_doc)
    return merged
