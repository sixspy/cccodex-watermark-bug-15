from app.db import get_db
from app.errors import ServiceError
from app.services.qi import qi_check


def trace_downstream(watermark_value: str, db_path: str | None = None) -> dict:
    value = (watermark_value or "").strip()
    if not value:
        raise ServiceError("水印值不能为空")
    with get_db(db_path) as conn:
        sources = conn.execute(
            "SELECT * FROM run_batches WHERE watermark_value=? ORDER BY id",
            (value,),
        ).fetchall()
        if not sources:
            raise ServiceError("未找到该水印值的盖印批次", 404)
        codes = [s["run_code"] for s in sources]
        placeholders = ",".join("?" for _ in codes)
        edges = conn.execute(
            f"SELECT * FROM lineage_edges WHERE upstream_run_code IN ({placeholders})",
            codes,
        ).fetchall()
        down_codes = sorted({e["downstream_run_code"] for e in edges})
        released = {
            r["run_code"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM release_records"
            ).fetchall()
        }
        downstream = []
        withheld = []
        if down_codes:
            ph2 = ",".join("?" for _ in down_codes)
            rows = conn.execute(
                f"SELECT * FROM run_batches WHERE run_code IN ({ph2}) ORDER BY id",
                down_codes,
            ).fetchall()
            for r in rows:
                q = qi_check(conn, r["run_code"])
                rec = released.get(r["run_code"])
                item = {
                    **dict(r),
                    "qi_complete": q["complete"],
                    "missing": q["missing"],
                    "broken_chain": q["broken_chain"],
                    "credential": q["credential"],
                    "released": rec is not None,
                    "release_credential": rec["credential"] if rec else None,
                }
                # 复验闸口：缺印却带放行态的记录不得被读到。
                if rec is not None and not q["complete"]:
                    withheld.append(
                        {
                            "run_code": r["run_code"],
                            "release_credential": rec["credential"],
                            "missing": q["missing"],
                        }
                    )
                    continue
                downstream.append(item)
        return {
            "watermark_value": value,
            "sources": [dict(s) for s in sources],
            "edges": [dict(e) for e in edges],
            "downstream": downstream,
            "withheld": withheld,
        }
