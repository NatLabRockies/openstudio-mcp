"""Unit tests for the file-transfer channel: signing, filename safety, archive
guards, and upload finalization. No server, no openstudio — pure logic.
"""
import base64
import hashlib
import json
import zipfile

import pytest

from mcp_server.skills.file_transfer import operations, signing
from mcp_server.skills.file_transfer.archive import guarded_extract

pytestmark = pytest.mark.unit

_MB = 1 << 20


def test_signed_token_roundtrip():
    # Validates: a token minted for (user, file, op) verifies and carries identity
    tok = signing.make_token("alice", "abc123", "u", 60)
    payload = signing.verify_token(tok, op="u")
    assert payload["u"] == "alice"
    assert payload["f"] == "abc123"
    assert payload["op"] == "u"


def test_tampered_signature_rejected():
    # Regression: route authorization IS the HMAC — a flipped sig must not verify
    tok = signing.make_token("alice", "abc", "u", 60)
    body, _sig = tok.split(".", 1)
    forged = f"{body}.{'A' * 43}"
    with pytest.raises(ValueError, match="signature"):
        signing.verify_token(forged)


def test_tampered_payload_rejected():
    # Regression: swapping the user in the body must invalidate the signature,
    # so a leaked token can't be edited to impersonate another tenant.
    tok = signing.make_token("alice", "abc", "u", 60)
    _body, sig = tok.split(".", 1)
    evil_body = base64.urlsafe_b64encode(
        json.dumps({"u": "bob", "f": "abc", "op": "u", "exp": 9_999_999_999},
                   separators=(",", ":"), sort_keys=True).encode(),
    ).decode().rstrip("=")
    with pytest.raises(ValueError, match="signature"):
        signing.verify_token(f"{evil_body}.{sig}")


def test_expired_token_rejected():
    # Validates: short-TTL URLs must stop working once expired
    tok = signing.make_token("alice", "abc", "u", -1)
    with pytest.raises(ValueError, match="expired"):
        signing.verify_token(tok)


def test_wrong_op_token_rejected():
    # Regression: an upload URL must not be replayable against the download route
    tok = signing.make_token("alice", "abc", "u", 60)
    with pytest.raises(ValueError, match="op"):
        signing.verify_token(tok, op="d")


@pytest.mark.parametrize(("raw", "expected"), [
    ("../../etc/passwd", "passwd"),
    ("/abs/model.osm", "model.osm"),
    ("..\\..\\win.osm", "win.osm"),
    ("", "upload.bin"),
    ("a b;c.osm", "a_b_c.osm"),
])
def test_sanitize_filename(raw, expected):
    # Regression: client filename must never become a path component
    out = operations._sanitize_filename(raw)
    assert out == expected
    assert "/" not in out and "\\" not in out and ".." not in out


def test_archive_rejects_path_escape(tmp_path):
    # Regression: a `..` zip entry must not write outside the extract dir
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escape.txt", "pwned")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "escape" in err.lower()
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_archive_rejects_symlink_member(tmp_path):
    # Regression: a symlink entry (e.g. -> /etc/shadow) must be refused
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 & 0xFFFF) << 16  # S_IFLNK | 0777
        zf.writestr(info, "/etc/shadow")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "symlink" in err.lower()


def test_archive_rejects_zip_bomb(tmp_path):
    # Validates: streamed uncompressed-size cap catches a high-ratio bomb
    z = tmp_path / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * (3 * _MB))
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "bomb" in err.lower()


def test_archive_rejects_too_many_entries(tmp_path):
    # Validates: entry-count cap bounds inode/CPU blowups
    z = tmp_path / "many.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(20):
            zf.writestr(f"f{i}.txt", "x")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=5)
    assert err is not None and "too many" in err.lower()


def test_archive_extracts_clean_tree(tmp_path):
    # Validates: a well-formed archive extracts with files intact, no error
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("m/measure.rb", "class M; end\n")
        zf.writestr("m/measure.xml", "<measure/>")
    out = tmp_path / "out"
    err = guarded_extract(z, out, max_uncompressed_bytes=_MB, max_entries=100)
    assert err is None
    assert (out / "m" / "measure.rb").read_text().startswith("class M")


def test_finalize_rejects_size_mismatch():
    # Regression: declared size must match streamed bytes (truncated/padded upload)
    req = operations.request_upload_op(filename="m.osm", size_bytes=10)
    assert req["ok"] is True
    fid = req["file_id"]
    entry = operations._entry_dir("local", fid)
    tmp = entry / ".incoming"
    tmp.write_bytes(b"short")  # 5 bytes, declared 10
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(b"short").hexdigest(), 5)
    assert res["ok"] is False
    assert res["status"] == 422
    assert "size mismatch" in res["error"]
    operations.delete_upload_op(fid)


def test_finalize_rejects_sha_mismatch():
    # Regression: a corrupted upload (right size, wrong bytes) must be rejected
    data = b"0123456789"
    req = operations.request_upload_op(filename="m.osm", size_bytes=len(data),
                                       sha256="deadbeef")
    fid = req["file_id"]
    entry = operations._entry_dir("local", fid)
    tmp = entry / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is False
    assert res["status"] == 422
    assert "sha256 mismatch" in res["error"]
    operations.delete_upload_op(fid)
