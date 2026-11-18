from app.db import get_db
from app.services.policy import (
    CLOSE_MIN_OBJECTS,
    COUNT_MODE,
    COUNT_MODE_LABEL,
)


def list_reports(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM visibility_reports ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def _empty_closed_count(conn, day: str) -> int:
    """已闭合但清单实有对象为 0 的批次（空已闭合）。"""
    return conn.execute(
        "SELECT COUNT(*) AS c FROM landing_batches b "
        "WHERE b.status='已闭合' AND b.biz_date<=? AND ("
        "  SELECT COUNT(*) FROM landing_objects o "
        "  WHERE o.batch_id=b.id AND o.status='已闭合'"
        ") = 0",
        (day,),
    ).fetchone()["c"]


def run_visibility(as_of_date: str, db_path: str | None = None) -> dict:
    day = (as_of_date or "").strip()
    if not day:
        day = "2026-11-16"
    with get_db(db_path) as conn:
        closed = conn.execute(
            "SELECT COUNT(*) AS c FROM landing_batches WHERE status='已闭合' AND biz_date<=?",
            (day,),
        ).fetchone()["c"]
        open_n = conn.execute(
            "SELECT COUNT(*) AS c FROM landing_batches WHERE status='收集中' AND biz_date<=?",
            (day,),
        ).fetchone()["c"]
        objects = conn.execute(
            "SELECT COUNT(*) AS c FROM landing_objects"
        ).fetchone()["c"]
        # 孤儿：对象所属批次已作废（基线种子无作废，恒 0；供后续切口）
        orphan = conn.execute(
            "SELECT COUNT(*) AS c FROM landing_objects o "
            "JOIN landing_batches b ON b.id=o.batch_id WHERE b.status='已作废'"
        ).fetchone()["c"]
        mismatch = conn.execute(
            "SELECT COUNT(*) AS c FROM landing_batches b "
            "WHERE b.status='已闭合' AND b.closed_object_count IS NOT NULL "
            "AND b.closed_object_count != ("
            "  SELECT COUNT(*) FROM landing_objects o WHERE o.batch_id=b.id AND o.status='已闭合'"
            ")"
        ).fetchone()["c"]
        empty_closed = _empty_closed_count(conn, day)
        summary = (
            f"截至 {day}：已闭合 {closed} 批，收集中 {open_n} 批，"
            f"对象 {objects}，孤儿 {orphan}，错位 {mismatch}，"
            f"空已闭合 {empty_closed}"
        )
        cur = conn.execute(
            "INSERT INTO visibility_reports("
            "as_of_date, closed_batch_count, open_batch_count, object_count, "
            "orphan_object_count, mismatch_count, empty_closed_batch_count, summary) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (day, closed, open_n, objects, orphan, mismatch, empty_closed, summary),
        )
        row = conn.execute(
            "SELECT * FROM visibility_reports WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def list_close_attempts(
    db_path: str | None = None, batch_id: int | None = None
) -> list[dict]:
    with get_db(db_path) as conn:
        if batch_id is None:
            rows = conn.execute(
                "SELECT * FROM close_attempts ORDER BY id DESC LIMIT 100"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM close_attempts WHERE batch_id=? ORDER BY id DESC",
                (batch_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def close_acceptance(db_path: str | None = None) -> dict:
    """解析验收台：闭合门槛、实有对象、空批拦截与空清单拒收一屏核齐。"""
    with get_db(db_path) as conn:
        batches = conn.execute(
            "SELECT * FROM landing_batches ORDER BY id"
        ).fetchall()
        rows = []
        blocked = 0
        empty_closed = 0
        for b in batches:
            registered = conn.execute(
                "SELECT COUNT(*) AS c FROM landing_objects "
                "WHERE batch_id=? AND status='已登记'",
                (b["id"],),
            ).fetchone()["c"]
            closed_n = conn.execute(
                "SELECT COUNT(*) AS c FROM landing_objects "
                "WHERE batch_id=? AND status='已闭合'",
                (b["id"],),
            ).fetchone()["c"]
            last = conn.execute(
                "SELECT * FROM close_attempts WHERE batch_id=? ORDER BY id DESC LIMIT 1",
                (b["id"],),
            ).fetchone()
            is_empty_closed = b["status"] == "已闭合" and int(closed_n) == 0
            if is_empty_closed:
                empty_closed += 1
            would_block = b["status"] == "收集中" and int(registered) < CLOSE_MIN_OBJECTS
            if would_block:
                blocked += 1
            rows.append(
                {
                    "batch_id": b["id"],
                    "zone_code": b["zone_code"],
                    "zone_name": b["zone_name"],
                    "biz_date": b["biz_date"],
                    "status": b["status"],
                    "registered_object_count": int(registered),
                    "closed_manifest_count": int(closed_n),
                    "closed_object_count": b["closed_object_count"],
                    "threshold": CLOSE_MIN_OBJECTS,
                    "count_mode": COUNT_MODE,
                    "count_mode_label": COUNT_MODE_LABEL,
                    "would_block_empty": would_block,
                    "empty_manifest": is_empty_closed,
                    "last_close_attempt": dict(last) if last else None,
                }
            )
        pulls = conn.execute(
            "SELECT * FROM manifest_pulls ORDER BY id DESC LIMIT 20"
        ).fetchall()
        return {
            "threshold": CLOSE_MIN_OBJECTS,
            "count_mode": COUNT_MODE,
            "count_mode_label": COUNT_MODE_LABEL,
            "empty_open_batch_count": blocked,
            "empty_closed_batch_count": empty_closed,
            "batches": rows,
            "recent_pulls": [dict(p) for p in pulls],
        }
