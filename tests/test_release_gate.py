import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from blacksheep.contents import JSONContent
from blacksheep.testing import TestClient

from app.db import get_db, init_db, migrate
from app.main import app
from app.services.errors import ServiceError
from app.services.gate import EXPECTED_GATE_SHA256, load_current_gate
from app.services.release import release_downstream


GATE_PATH = Path(__file__).resolve().parent.parent / "app" / "gates" / "qi_check_gate.json"


def _db(tmp_path: Path) -> str:
    path = str(tmp_path / "gate.db")
    init_db(path)
    return path


def _stamp_all(db: str, codes, value_prefix="WM-GATE") -> None:
    with get_db(db) as conn:
        for code in codes:
            conn.execute(
                "UPDATE run_batches SET status='已盖印', watermark_value=?, "
                "stamped_at=datetime('now') WHERE run_code=?",
                (f"{value_prefix}-{code}", code),
            )


def _release_row(db: str, code: str):
    with get_db(db) as conn:
        return conn.execute(
            "SELECT * FROM release_records WHERE run_code=?", (code,)
        ).fetchone()


def test_gate_file_is_pinned_and_immutable():
    gate = load_current_gate()
    raw = GATE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_GATE_SHA256
    assert gate["gate_id"] == "qi-check-downstream"
    assert gate["immutable"] is True
    # 旧门槛必须已进只读历史，不再作为现行凭证
    history = list((GATE_PATH.parent / "history").glob("*.json"))
    assert history, "旧门槛未迁入只读历史"


def test_missing_stamp_is_blocked_and_nothing_written(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ServiceError) as exc:
        release_downstream("gmv-20261114-01", db_path=db)
    assert exc.value.status_code == 409
    assert "缺印" in exc.value.message
    assert _release_row(db, "gmv-20261114-01") is None

    # 页面四处同源：下游附页应标缺印
    from app.services.release import release_overview

    ov = release_overview(db)
    row = next(r for r in ov["downstream"] if r["run_code"] == "gmv-20261114-01")
    assert row["qi_complete"] is False
    assert row["missing"]
    assert not row["released"]
    assert ov["progress"] == []


def test_full_chain_release_records_credential(tmp_path):
    db = _db(tmp_path)
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    result = release_downstream("gmv-20261114-01", db_path=db)
    assert result["released"] is True
    assert result["credential"] == result["gate"]["credential"] + ":" + result[
        "credential_sha256"
    ][:16]
    row = _release_row(db, "gmv-20261114-01")
    assert row["gate_id"] == "qi-check-downstream"
    assert row["credential"] == result["credential"]

    with pytest.raises(ServiceError):
        release_downstream("gmv-20261114-01", db_path=db)


def test_stale_credential_rejected(tmp_path):
    db = _db(tmp_path)
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    with pytest.raises(ServiceError) as exc:
        release_downstream(
            "gmv-20261114-01", db_path=db, gate_credential="qi-check-downstream@1#deadbeef"
        )
    assert "凭证" in exc.value.message
    assert _release_row(db, "gmv-20261114-01") is None


def test_broken_chain_blocked(tmp_path):
    db = _db(tmp_path)
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO lineage_edges(upstream_run_code, downstream_run_code) "
            "VALUES ('ghost-orphan-01','gmv-20261114-01')"
        )
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    with pytest.raises(ServiceError) as exc:
        release_downstream("gmv-20261114-01", db_path=db)
    assert "断链" in exc.value.message


def test_legacy_silent_release_quarantined(tmp_path):
    db = _db(tmp_path)
    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('released_gmv-20261114-01','1')"
        )
    migrate(db)
    with get_db(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) c FROM meta WHERE key LIKE 'released\\_%' ESCAPE '\\'"
            ).fetchone()["c"]
            == 0
        )
        hist = conn.execute(
            "SELECT * FROM legacy_release_history WHERE run_code='gmv-20261114-01'"
        ).fetchone()
        assert hist is not None
        assert _release_row(db, "gmv-20261114-01") is None
        # 只读历史不可改不可删
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE legacy_release_history SET reason='x'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM legacy_release_history")


def test_trace_withholds_missing_stamp_release(tmp_path):
    """顺藤复验：即便库里有缺印放行行，追索也不得读到。"""
    db = _db(tmp_path)
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    release_downstream("gmv-20261114-01", db_path=db)
    # 事后把一段上游印记抹掉，模拟“缺印已放行”的脏记录
    with get_db(db) as conn:
        conn.execute(
            "UPDATE run_batches SET status='待盖印', watermark_value=NULL "
            "WHERE run_code='pay-20261114-01'"
        )
    from app.services.trace import trace_downstream

    result = trace_downstream("WM-ORD-131", db_path=db)
    handled_codes = [d["run_code"] for d in result["downstream"]]
    if "gmv-20261114-01" in handled_codes:
        d = next(x for x in result["downstream"] if x["run_code"] == "gmv-20261114-01")
        assert d["qi_complete"] is False
    else:
        assert any(w["run_code"] == "gmv-20261114-01" for w in result["withheld"])


def test_concurrent_release_single_write(tmp_path):
    db = _db(tmp_path)
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    outcome: list[str] = []

    def worker():
        try:
            release_downstream("gmv-20261114-01", db_path=db)
            outcome.append("ok")
        except ServiceError as exc:
            outcome.append("err:" + exc.message)

    threads = []
    for _ in range(2):
        t = __import__("threading").Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert sorted(o.split(":")[0] for o in outcome) == ["err", "ok"]
    with get_db(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) c FROM release_records WHERE run_code='gmv-20261114-01'"
            ).fetchone()["c"]
            == 1
        )


def test_tampered_gate_file_stops_release(tmp_path, monkeypatch):
    from app.config import Config

    fake = tmp_path / "gate.json"
    fake.write_text('{"gate_id":"qi-check-downstream","gate_version":1}', encoding="utf-8")
    monkeypatch.setattr(Config, "GATE_FILE", fake)

    with pytest.raises(ServiceError) as exc:
        load_current_gate()
    assert exc.value.status_code == 503
    assert "改动" in exc.value.message


def test_override_gate_blocks_missing_stamps(tmp_path, monkeypatch):
    """换完现行门槛后，缺印批同样不能入库（选边不得绕过齐检）。"""
    from app.config import Config

    db = _db(tmp_path)
    fake = tmp_path / "gate.json"
    fake.write_text(GATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(Config, "GATE_FILE", fake)

    with pytest.raises(ServiceError) as exc:
        release_downstream("gmv-20261114-01", db_path=db)
    assert "缺印" in exc.value.message


def test_missing_stamp_already_released_stops_all(tmp_path):
    """一旦出现缺印已放行记录，放行动作整体停止。"""
    db = _db(tmp_path)
    _stamp_all(db, ["ord-20261114-01", "pay-20261114-01", "gmv-20261114-01"])
    release_downstream("gmv-20261114-01", db_path=db)

    with get_db(db) as conn:
        conn.execute(
            "INSERT INTO run_batches(table_name, run_code, biz_date, status) "
            "VALUES ('dm_gmv_d','gmv-20261115-01','2026-11-15','待盖印')"
        )
        conn.execute(
            "INSERT INTO lineage_edges(upstream_run_code, downstream_run_code) "
            "VALUES ('gmv-20261114-01','gmv-20261115-01')"
        )
    _stamp_all(db, ["gmv-20261115-01"])

    # 事后把一段上游印记抹掉：已放行记录不再齐备
    with get_db(db) as conn:
        conn.execute(
            "UPDATE run_batches SET status='待盖印', watermark_value=NULL "
            "WHERE run_code='ord-20261114-01'"
        )

    from app.services.release import release_overview

    ov = release_overview(db)
    assert ov["stop"] is True
    assert any(a["run_code"] == "gmv-20261114-01" for a in ov["anomaly"])

    with pytest.raises(ServiceError) as exc:
        release_downstream("gmv-20261115-01", db_path=db)
    assert exc.value.status_code == 503
    assert "停止放行" in exc.value.message


@pytest.mark.asyncio
async def test_api_gate_and_release_flow(tmp_path):
    db = str(tmp_path / "api.db")
    os.environ["DATABASE_PATH"] = db
    init_db(db)
    await app.start()
    client = TestClient(app)
    try:
        login = await client.post(
            "/api/login", content=JSONContent({"username": "admin", "password": "123456"})
        )
        cookies = {
            k: getattr(v, "value", v) for k, v in (getattr(login, "cookies", {}) or {}).items()
        }

        gate = await client.get("/api/gate", cookies=cookies)
        assert gate.status == 200
        gbody = await gate.json()
        assert gbody["gate"]["gate_id"] == "qi-check-downstream"
        assert gbody["history"]

        blocked = await client.post(
            "/api/release",
            content=JSONContent({"run_code": "gmv-20261114-01"}),
            cookies=cookies,
        )
        assert blocked.status == 409
        assert "缺印" in (await blocked.json())["error"]

        ov = await client.get("/api/release/overview", cookies=cookies)
        obody = await ov.json()
        assert obody["stop"] is False
        assert obody["gate"]["credential"].startswith("qi-check-downstream@1#")
        assert any(r["missing"] for r in obody["stamps"])
    finally:
        await app.stop()
