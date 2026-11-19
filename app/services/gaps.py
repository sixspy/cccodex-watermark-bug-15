from app.db import get_db
from app.services.qi import is_stamped


def list_reports(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM gap_reports ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def run_gap_report(as_of_date: str, db_path: str | None = None) -> dict:
    day = (as_of_date or "").strip() or "2026-11-16"
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM run_batches WHERE biz_date<=? AND status!='已作废' ORDER BY id",
            (day,),
        ).fetchall()
        missing = [dict(r) for r in rows if not is_stamped(r)]
        expected = len(rows)
        stamped = expected - len(missing)
        gap = len(missing)
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
        result = dict(row)
        result["missing"] = missing
        return result
