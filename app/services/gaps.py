from app.db import get_db


def list_reports(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM gap_reports ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def run_gap_report(as_of_date: str, db_path: str | None = None) -> dict:
    day = (as_of_date or "").strip() or "2026-11-16"
    with get_db(db_path) as conn:
        released = conn.execute(
            "SELECT COUNT(*) AS c FROM meta WHERE key LIKE 'released_%'"
        ).fetchone()["c"]
        expected = conn.execute(
            "SELECT COUNT(*) AS c FROM run_batches WHERE biz_date<=? AND status!='已作废'",
            (day,),
        ).fetchone()["c"] + released
        stamped = conn.execute(
            "SELECT COUNT(*) AS c FROM run_batches WHERE biz_date<=? AND status='已盖印'",
            (day,),
        ).fetchone()["c"]
        gap = expected - stamped
        summary = (
            f"截至 {day}：应盖印 {expected}，已盖印 {stamped}，缺口 {gap}"
        )
        cur = conn.execute(
            "INSERT INTO gap_reports(as_of_date, expected_count, stamped_count, gap_count, summary) "
            "VALUES (?,?,?,?,?)",
            (day, expected, stamped, gap, summary),
        )
        row = conn.execute(
            "SELECT * FROM gap_reports WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
