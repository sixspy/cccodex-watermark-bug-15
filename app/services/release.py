from app.db import get_db
from app.services.errors import ServiceError


def release_downstream(run_code: str, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        batch = conn.execute(
            "SELECT * FROM run_batches WHERE run_code=?", (run_code,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404)
        # silent: no check that watermark_value present / upstream complete
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (f"released_{run_code}", "1"),
        )
        return {"run_code": run_code, "released": True, "watermark_value": batch["watermark_value"]}
