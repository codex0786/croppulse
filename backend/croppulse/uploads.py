"""Photo upload validation and metadata stripping (standard library only).

* Accepts JPEG and PNG, identified by magic bytes — the client-supplied content type
  and filename are ignored.
* Enforces a size limit.
* Removes JPEG APPn metadata segments (EXIF/XMP, which can contain GPS coordinates)
  and PNG ancillary text/eXIf chunks before storage.
* Stores under a random name outside any web-served directory.
"""

from __future__ import annotations

import hashlib
import secrets
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class UploadError(ValueError):
    pass


@dataclass
class StoredFile:
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str
    metadata_stripped: bool


def sniff(data: bytes) -> str:
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(PNG_MAGIC):
        return "image/png"
    raise UploadError("Only JPEG or PNG photos are accepted")


def strip_jpeg_metadata(data: bytes) -> bytes:
    out = bytearray(data[:2])
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            raise UploadError("Corrupt JPEG")
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: copy the rest verbatim
            out += data[i:]
            return bytes(out)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i : i + 2]
            i += 2
            continue
        if i + 4 > len(data):
            raise UploadError("Corrupt JPEG")
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        segment = data[i : i + 2 + length]
        # Drop APP1..APP15 (EXIF, XMP, ICC kept? ICC is APP2 — dropped; colour fidelity is not needed here) and COM.
        if not (0xE1 <= marker <= 0xEF or marker == 0xFE):
            out += segment
        i += 2 + length
    raise UploadError("Corrupt JPEG (no image data)")


def strip_png_metadata(data: bytes) -> bytes:
    out = bytearray(PNG_MAGIC)
    i = len(PNG_MAGIC)
    drop = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}
    while i < len(data):
        if i + 8 > len(data):
            raise UploadError("Corrupt PNG")
        (length,) = struct.unpack(">I", data[i : i + 4])
        ctype = data[i + 4 : i + 8]
        chunk = data[i : i + 12 + length]
        if len(chunk) != 12 + length:
            raise UploadError("Corrupt PNG")
        (crc,) = struct.unpack(">I", chunk[-4:])
        if zlib.crc32(chunk[4:-4]) & 0xFFFFFFFF != crc:
            raise UploadError("Corrupt PNG (bad CRC)")
        if ctype not in drop:
            out += chunk
        i += 12 + length
        if ctype == b"IEND":
            return bytes(out)
    raise UploadError("Corrupt PNG (no IEND)")


def store_photo(data: bytes, upload_dir: Path, max_bytes: int) -> StoredFile:
    if len(data) == 0:
        raise UploadError("Empty file")
    if len(data) > max_bytes:
        raise UploadError(f"Photo exceeds {max_bytes // (1024 * 1024)} MB")
    ctype = sniff(data)
    clean = strip_jpeg_metadata(data) if ctype == "image/jpeg" else strip_png_metadata(data)
    key = secrets.token_hex(16) + (".jpg" if ctype == "image/jpeg" else ".png")
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / key).write_bytes(clean)
    return StoredFile(key, ctype, len(clean), hashlib.sha256(clean).hexdigest(), True)
