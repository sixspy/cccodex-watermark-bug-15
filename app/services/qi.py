"""齐检：印记值齐备判定 + 齐检凭证的唯一来源。

齐印统计、放行动作、下游表附页、放行进度全部调用这里，
避免“齐印说齐、放行说可放”两套口径。凭证由门槛身份与
实际印记值共同计算：任一上游缺印，凭证就拼不出来。
"""

import hashlib
import json
import sqlite3

from app.errors import ServiceError
from app.services.gate import load_current_gate


def is_stamped(batch: sqlite3.Row | dict | None) -> bool:
    """齐检口径的唯一“已盖章”定义：状态已盖印且印记值非空。"""
    if not batch:
        return False
    value = (batch["watermark_value"] or "").strip()
    return batch["status"] == "已盖印" and bool(value)


# 兼容旧内部名
_stamped = is_stamped


def upstream_codes(conn: sqlite3.Connection, run_code: str) -> list[str]:
    """顺藤向上收集全部上游运行码（含多层），断链节点也保留在结果里。"""
    rows = conn.execute(
        """
        WITH RECURSIVE up(code) AS (
          SELECT upstream_run_code FROM lineage_edges WHERE downstream_run_code = ?
          UNION
          SELECT e.upstream_run_code
          FROM lineage_edges e JOIN up ON e.downstream_run_code = up.code
        )
        SELECT code FROM up ORDER BY code
        """,
        (run_code,),
    ).fetchall()
    return [r["code"] for r in rows]


def _row_for(conn: sqlite3.Connection, run_code: str):
    return conn.execute(
        "SELECT * FROM run_batches WHERE run_code=?", (run_code,)
    ).fetchone()


def _hex_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def qi_check(conn: sqlite3.Connection, run_code: str) -> dict:
    """计算一个批次的齐检结果与齐检凭证。

    缺印（本批或上游未盖印/印记值为空）与断链（上游无批次记录）
    都算不齐；凭证只在全齐时生成。
    """
    gate = load_current_gate()
    self_row = _row_for(conn, run_code)
    if not self_row:
        raise ServiceError("批次不存在", 404)

    missing: list[dict] = []
    broken: list[str] = []
    checked: list[dict] = []

    if not _stamped(self_row):
        missing.append(
            {
                "run_code": run_code,
                "table_name": self_row["table_name"],
                "scope": "本批",
                "status": self_row["status"],
                "watermark_value": self_row["watermark_value"],
            }
        )
    else:
        checked.append(
            {
                "run_code": run_code,
                "table_name": self_row["table_name"],
                "watermark_value": self_row["watermark_value"].strip(),
                "scope": "本批",
            }
        )

    for code in upstream_codes(conn, run_code):
        row = _row_for(conn, code)
        if row is None:
            broken.append(code)
            missing.append(
                {
                    "run_code": code,
                    "table_name": None,
                    "scope": "上游",
                    "status": "断链",
                    "watermark_value": None,
                }
            )
            continue
        if not _stamped(row):
            missing.append(
                {
                    "run_code": code,
                    "table_name": row["table_name"],
                    "scope": "上游",
                    "status": row["status"],
                    "watermark_value": row["watermark_value"],
                }
            )
        else:
            checked.append(
                {
                    "run_code": code,
                    "table_name": row["table_name"],
                    "watermark_value": row["watermark_value"].strip(),
                    "scope": "上游",
                }
            )

    complete = not missing
    credential = None
    credential_sha256 = None
    if complete:
        canonical = json.dumps(
            {
                "gate": gate["credential"],
                "batch": run_code,
                "required": sorted(
                    [c["run_code"], c["watermark_value"]] for c in checked
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        credential_sha256 = _hex_digest(canonical)
        credential = f"{gate['credential']}:{credential_sha256[:16]}"

    return {
        "run_code": run_code,
        "table_name": self_row["table_name"],
        "status": self_row["status"],
        "watermark_value": self_row["watermark_value"],
        "complete": complete,
        "missing": missing,
        "broken_chain": broken,
        "checked": checked,
        "credential": credential,
        "credential_sha256": credential_sha256,
        "gate": {
            "gate_id": gate["gate_id"],
            "gate_version": gate["gate_version"],
            "title": gate["title"],
            "requirement": gate["requirement"],
            "credential": gate["credential"],
            "sha256": gate["sha256"],
        },
    }
