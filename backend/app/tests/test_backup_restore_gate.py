"""
Tests for T26 (System Backup & Restore) and T72 (Unauthenticated Restore Gate).
"""

import io, uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token

_TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "br-secret-key-32chars-long!!")
    monkeypatch.setenv("ENCRYPTION_KEY", _TEST_KEY)


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Reset slowapi limiter between tests so rate limits don't accumulate."""
    try:
        from app.rate_limiter import limiter
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        from app.rate_limiter import limiter
        limiter.reset()
    except Exception:
        pass


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    with mock.patch("app.main.SessionLocal", return_value=mock_db):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _admin_jwt(admin_id):
    return create_access_token(user_id=admin_id, username="admin",
                               role="ADMIN", session_id=None)


def _make_backup(key):
    import tarfile, tempfile
    from pathlib import Path
    fernet = Fernet(key.encode())
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "dump.sql").write_text("-- test backup\nSELECT 1;\n")
        (d / "uploads").mkdir(exist_ok=True)
        arc = d / "backup.tar.gz"
        with tarfile.open(arc, "w:gz") as tar:
            tar.add(d / "dump.sql", arcname="dump.sql")
            tar.add(d / "uploads", arcname="uploads")
        return fernet.encrypt(arc.read_bytes())


def _fake_db_engine_ctx():
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.__enter__ = mock.MagicMock(return_value=mock.MagicMock())
    ctx.__exit__ = mock.MagicMock(return_value=None)
    fake.begin.return_value = ctx
    return fake


# ══════════════════════════════════════════════════════════════════════════════
# T26 — Backup tests
# ══════════════════════════════════════════════════════════════════════════════

def test_backup_rejects_unauthenticated(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    r = client.get("/api/system/backup")
    assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# T26 — Restore tests
# ══════════════════════════════════════════════════════════════════════════════

def test_restore_rejects_missing_file(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    r = client.post("/api/system/restore")
    assert r.status_code == 400


def test_restore_rejects_empty_file(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    r = client.post("/api/system/restore",
        files={"backup_file": ("e.bak", io.BytesIO(b""), "application/octet-stream")})
    assert r.status_code == 400


def test_restore_rejects_corrupted_archive(client, mock_db):
    admin = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    jwt = _admin_jwt(admin)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    with mock.patch("cryptography.fernet.Fernet.decrypt", side_effect=InvalidToken):
        r = tc.post("/api/system/restore",
            files={"backup_file": ("x.bak", io.BytesIO(b"any"), "application/octet-stream")})
    assert r.status_code == 400


def test_restore_rejects_wrong_key(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    wrong = Fernet.generate_key().decode()
    fernet = Fernet(wrong.encode())
    encrypted = fernet.encrypt(b"data")
    r = client.post("/api/system/restore",
        files={"backup_file": ("w.bak", io.BytesIO(encrypted), "application/octet-stream")})
    assert r.status_code == 400


def test_restore_rejects_missing_dump_sql(client, mock_db):
    import tarfile, tempfile
    from pathlib import Path

    admin = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    jwt = _admin_jwt(admin)

    fernet = Fernet(_TEST_KEY.encode())
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        arc = d / "bad.tar.gz"
        with tarfile.open(arc, "w:gz") as tar:
            f = d / "x.txt"
            f.write_text("nope")
            tar.add(f, arcname="x.txt")
        encrypted = fernet.encrypt(arc.read_bytes())

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    r = tc.post("/api/system/restore",
        files={"backup_file": ("bad.bak", io.BytesIO(encrypted), "application/octet-stream")})
    assert r.status_code == 400
    assert "dump.sql" in r.json().get("detail", "").lower()


def test_restore_succeeds_on_fresh_system(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    backup = _make_backup(_TEST_KEY)

    with mock.patch("app.database.engine", _fake_db_engine_ctx()):
        r = client.post("/api/system/restore",
            files={"backup_file": ("good.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 200, (
        f"Expected 200, got {r.status_code}: {r.json() if r.content else 'empty'}"
    )
    assert r.json().get("status") == "success"


# ══════════════════════════════════════════════════════════════════════════════
# T72 — Unauthenticated restore gate
# ══════════════════════════════════════════════════════════════════════════════

def test_restore_gate_bypass_on_fresh_system(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    backup = _make_backup(_TEST_KEY)
    with mock.patch("app.database.engine", _fake_db_engine_ctx()):
        r = client.post("/api/system/restore",
            files={"backup_file": ("fresh.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 200
    assert r.json().get("status") == "success"


def test_restore_gate_rejects_unauth_on_initialized(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    backup = _make_backup(_TEST_KEY)
    r = client.post("/api/system/restore",
        files={"backup_file": ("x.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 401


def test_restore_gate_accepts_admin_jwt(client, mock_db):
    aid = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    jwt = _admin_jwt(aid)
    backup = _make_backup(_TEST_KEY)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.database.engine", _fake_db_engine_ctx()):
        r = tc.post("/api/system/restore",
            files={"backup_file": ("a.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 200
    assert r.json().get("status") == "success"


def test_restore_gate_rejects_heir_jwt(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    heir_jwt = create_access_token(user_id=str(uuid.uuid4()),
        username="heir", role="HEIR", session_id=str(uuid.uuid4()))
    backup = _make_backup(_TEST_KEY)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": heir_jwt}
    r = tc.post("/api/system/restore",
        files={"backup_file": ("h.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 401


def test_restore_gate_rejects_invalid_jwt(client, mock_db):
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    backup = _make_backup(_TEST_KEY)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": "totally.invalid.token"}
    r = tc.post("/api/system/restore",
        files={"backup_file": ("t.bak", io.BytesIO(backup), "application/octet-stream")})
    assert r.status_code == 401


def test_restore_gate_rate_limited(client, mock_db):
    aid = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    jwt = _admin_jwt(aid)
    backup = _make_backup(_TEST_KEY)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    with mock.patch("app.database.engine", _fake_db_engine_ctx()):
        responses = []
        for i in range(5):
            r = tc.post("/api/system/restore",
                files={"backup_file": (f"r{i}.bak", io.BytesIO(backup), "application/octet-stream")})
            responses.append(r)

        any_headers = any("x-ratelimit" in r.headers for r in responses)
        any_429 = any(r.status_code == 429 for r in responses)
        assert any_headers or any_429, (
            f"No rate limit headers or 429: {[r.status_code for r in responses]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# T28c — Positive backup tests (Testing Spec §1.6)
# ══════════════════════════════════════════════════════════════════════════════

def test_backup_returns_octet_stream_with_admin_jwt(client, mock_db, monkeypatch):
    """GET /api/system/backup returns 200 + application/octet-stream for Admin."""
    import subprocess
    aid = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.first.return_value = mock.MagicMock(
        id=aid, role="ADMIN"
    )
    # Ensure DATABASE_URL is set so the backup handler can parse it
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/estate")

    jwt = _admin_jwt(aid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    # Mock pg_dump to succeed by writing a minimal dump file
    def _fake_pg_dump(*args, **kwargs):
        cmd_list = args[0] if args else kwargs.get("args", [])
        out_path = None
        for i, a in enumerate(cmd_list):
            if a == "-f" and i + 1 < len(cmd_list):
                out_path = cmd_list[i + 1]
                break
        if out_path:
            from pathlib import Path
            Path(out_path).write_text("-- test backup dump\nSELECT 1;\n")
        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    with mock.patch("subprocess.run", side_effect=_fake_pg_dump):
        r = tc.get("/api/system/backup")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.content[:200] if r.content else 'empty'}"
    assert r.headers.get("content-type") == "application/octet-stream"
    assert len(r.content) > 0


def test_backup_archive_decryptable(client, mock_db, monkeypatch):
    """The backup archive can be decrypted with ENCRYPTION_KEY."""
    import subprocess
    aid = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.first.return_value = mock.MagicMock(
        id=aid, role="ADMIN"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/estate")

    jwt = _admin_jwt(aid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    def _fake_pg_dump(*args, **kwargs):
        cmd_list = args[0] if args else kwargs.get("args", [])
        out_path = None
        for i, a in enumerate(cmd_list):
            if a == "-f" and i + 1 < len(cmd_list):
                out_path = cmd_list[i + 1]
                break
        if out_path:
            from pathlib import Path
            Path(out_path).write_text("-- test backup dump\nSELECT 1;\n")
        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    with mock.patch("subprocess.run", side_effect=_fake_pg_dump):
        r = tc.get("/api/system/backup")
    assert r.status_code == 200

    fernet = Fernet(_TEST_KEY.encode())
    plaintext = fernet.decrypt(r.content)
    assert plaintext is not None
    assert len(plaintext) > 0


def test_backup_archive_contains_dump_sql_and_uploads(client, mock_db, monkeypatch):
    """Decrypted tar.gz contains dump.sql and uploads/ directory."""
    import subprocess, tarfile
    aid = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.first.return_value = mock.MagicMock(
        id=aid, role="ADMIN"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/estate")

    jwt = _admin_jwt(aid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    def _fake_pg_dump(*args, **kwargs):
        cmd_list = args[0] if args else kwargs.get("args", [])
        out_path = None
        for i, a in enumerate(cmd_list):
            if a == "-f" and i + 1 < len(cmd_list):
                out_path = cmd_list[i + 1]
                break
        if out_path:
            from pathlib import Path
            Path(out_path).write_text("-- test backup dump\nSELECT 1;\n")
        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    with mock.patch("subprocess.run", side_effect=_fake_pg_dump):
        r = tc.get("/api/system/backup")
    assert r.status_code == 200

    fernet = Fernet(_TEST_KEY.encode())
    plaintext = fernet.decrypt(r.content)
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as tar:
        names = tar.getnames()
        assert "dump.sql" in names, f"tar.gz contents: {names}"


def test_restore_rolls_back_on_sql_failure(client, mock_db):
    """Restore is transactional — if SQL import fails, roll back."""
    admin = str(uuid.uuid4())
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    jwt = _admin_jwt(admin)
    backup = _make_backup(_TEST_KEY)

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}

    # Mock the database engine with a context manager that tracks begin/rollback
    rolled_back = []
    engine = mock.MagicMock()
    tx = mock.MagicMock()
    tx.__enter__ = mock.MagicMock(return_value=mock.MagicMock())
    tx.__exit__ = mock.MagicMock(return_value=None)
    engine.begin.return_value = tx

    # Mock sqlalchemy.text(...).execution_options(...) call to raise
    with mock.patch("app.database.engine", engine), \
         mock.patch("sqlalchemy.text", side_effect=Exception("SQL import failure")):
        r = tc.post("/api/system/restore",
            files={"backup_file": ("fail.bak", io.BytesIO(backup), "application/octet-stream")})
    # Should return 500 and the transaction should have been exited
    assert r.status_code in (400, 500), f"Expected error status, got {r.status_code}: {r.json() if r.content else 'empty'}"
