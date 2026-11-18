from app.db import get_db


def list_templates(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM watermark_templates WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM watermark_templates ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]
