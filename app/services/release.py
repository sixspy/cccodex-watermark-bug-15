"""放行动作：按齐检凭证一次落成，缺印即拦截。

整段动作在 BEGIN IMMEDIATE 排他写锁内完成：
读取门槛 → 齐检复算 → 写放行态行，三点之间没有窗口。
两侧仓管同时抢放行时，后到者在锁上排队，读到的已是已放行态。
"""

import sqlite3

from app.db import get_db_exclusive
from app.errors import ServiceError
from app.services.qi import qi_check


def _qi_or_none(conn: sqlite3.Connection, code: str) -> dict | None:
    try:
        return qi_check(conn, code)
    except ServiceError as exc:
        if exc.status_code == 404:
            return None
        raise


def _audit_releases(conn: sqlite3.Connection) -> list[dict]:
    """齐印与可放行同源自检：任何已放行行的齐检不再齐备即视为异常。"""
    anomalies: list[dict] = []
    for rec in conn.execute("SELECT * FROM release_records ORDER BY id").fetchall():
        q = _qi_or_none(conn, rec["run_code"])
        if q is None:
            anomalies.append(
                {
                    "run_code": rec["run_code"],
                    "credential": rec["credential"],
                    "missing": [],
                    "reasons": ["批次已不存在"],
                }
            )
        elif not q["complete"]:
            anomalies.append(
                {
                    "run_code": rec["run_code"],
                    "credential": rec["credential"],
                    "missing": q["missing"],
                }
            )
    return anomalies


def release_downstream(
    run_code: str,
    db_path: str | None = None,
    *,
    gate_credential: str | None = None,
) -> dict:
    code = (run_code or "").strip()
    if not code:
        raise ServiceError("运行码不能为空")

    with get_db_exclusive(db_path) as conn:
        anomalies = _audit_releases(conn)
        if anomalies:
            raise ServiceError(
                f"检测到缺印已放行（{anomalies[0]['run_code']}），已停止放行", 503
            )

        existing = conn.execute(
            "SELECT * FROM release_records WHERE run_code=?", (code,)
        ).fetchone()
        if existing:
            raise ServiceError("批次已放行", 409)

        result = qi_check(conn, code)

        if not result["complete"]:
            first = result["missing"][0]
            if first["status"] == "断链":
                raise ServiceError(
                    f"上游断链：{first['run_code']} 无批次记录，禁止放行", 409
                )
            where = "本批" if first["scope"] == "本批" else "上游批次"
            raise ServiceError(
                f"{where} {first['run_code']} 缺印，禁止放行", 409
            )

        if gate_credential and gate_credential != result["credential"]:
            raise ServiceError("齐检凭证不一致，禁止放行", 409)

        conn.execute(
            """
            INSERT INTO release_records(
              run_code, gate_id, gate_version, gate_sha256,
              credential, watermark_value
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                code,
                result["gate"]["gate_id"],
                result["gate"]["gate_version"],
                result["gate"]["sha256"],
                result["credential"],
                result["watermark_value"],
            ),
        )
        row = conn.execute(
            "SELECT * FROM release_records WHERE run_code=?", (code,)
        ).fetchone()
        return {
            "run_code": code,
            "released": True,
            "watermark_value": result["watermark_value"],
            "credential": result["credential"],
            "credential_sha256": result["credential_sha256"],
            "gate": result["gate"],
            "release": dict(row),
            "mirror": mirror_payload(conn, code),
        }


def mirror_payload(conn: sqlite3.Connection, run_code: str) -> dict:
    """页面四处联动所需的最小镜像：缺印行、门槛芯片、放行进度。"""
    result = qi_check(conn, run_code)
    releases = conn.execute(
        "SELECT * FROM release_records ORDER BY id"
    ).fetchall()
    return {
        "qi": result,
        "release": next(
            (dict(r) for r in releases if r["run_code"] == run_code), None
        ),
        "progress": [
            {
                "run_code": r["run_code"],
                "credential": r["credential"],
                "gate_version": r["gate_version"],
                "released_at": r["released_at"],
            }
            for r in releases
        ],
    }


def list_releases(db_path: str | None = None) -> list[dict]:
    from app.db import get_db

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM release_records ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def release_overview(db_path: str | None = None) -> dict:
    """放行进度 + 下游表附页 + 印记值卡片，统一从齐检口径生成。"""
    from app.db import get_db
    from app.services.gate import load_current_gate, load_history
    from app.services.qi import is_stamped

    gate = load_current_gate()
    with get_db(db_path) as conn:
        batches = conn.execute(
            "SELECT * FROM run_batches ORDER BY id"
        ).fetchall()
        releases = {
            r["run_code"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM release_records ORDER BY id"
            ).fetchall()
        }
        downstream_codes: set[str] = {
            e["downstream_run_code"]
            for e in conn.execute("SELECT * FROM lineage_edges").fetchall()
        }
        qi_cache: dict[str, dict | None] = {}

        def _qi(code: str) -> dict | None:
            if code not in qi_cache:
                qi_cache[code] = _qi_or_none(conn, code)
            return qi_cache[code]

        downstream_rows = []
        for b in batches:
            if b["run_code"] not in downstream_codes:
                continue
            q = _qi(b["run_code"]) or {}
            downstream_rows.append(
                {
                    **dict(b),
                    "qi_complete": bool(q.get("complete")),
                    "credential": q.get("credential"),
                    "missing": q.get("missing", []),
                    "released": b["run_code"] in releases,
                    "release": releases.get(b["run_code"]),
                }
            )
        stamps = [
            {
                "run_code": b["run_code"],
                "table_name": b["table_name"],
                "watermark_value": b["watermark_value"],
                "status": b["status"],
                "missing": not is_stamped(b),
            }
            for b in batches
        ]
        anomaly: list[dict] = []
        for rec in releases.values():
            reasons = []
            q = _qi(rec["run_code"])
            if q is None:
                reasons.append("批次已不存在")
            elif not q["complete"]:
                reasons.append("齐检不齐")
            if rec["gate_sha256"] != gate["sha256"]:
                reasons.append("门槛摘要不符")
            if (
                rec["gate_id"] != gate["gate_id"]
                or rec["gate_version"] != gate["gate_version"]
            ):
                reasons.append("门槛版本不符")
            if reasons:
                anomaly.append(
                    {
                        "run_code": rec["run_code"],
                        "credential": rec["credential"],
                        "reasons": reasons,
                    }
                )
        return {
            "gate": {
                "gate_id": gate["gate_id"],
                "gate_version": gate["gate_version"],
                "title": gate["title"],
                "requirement": gate["requirement"],
                "credential": gate["credential"],
                "sha256": gate["sha256"],
                "file_readonly": gate.get("file_readonly", False),
            },
            "gate_history": load_history(),
            "stamps": stamps,
            "downstream": downstream_rows,
            "progress": [
                {
                    **r,
                    "qi_complete": bool(
                        (_qi(r["run_code"]) or {}).get("complete")
                    ),
                }
                for r in releases.values()
            ],
            "anomaly": anomaly,
            "stop": bool(anomaly),
        }
