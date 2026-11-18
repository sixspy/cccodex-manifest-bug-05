from app.db import get_db
from app.services.objects import ServiceError
from app.services.policy import (
    CLOSE_MIN_OBJECTS,
    COUNT_MODE,
    COUNT_MODE_LABEL,
    EMPTY_BATCH_CODE,
    evaluate_close_gate,
)


def _count_registered(conn, batch_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM landing_objects "
        "WHERE batch_id=? AND status='已登记'",
        (batch_id,),
    ).fetchone()
    return int(row["c"])


def _record_attempt(
    conn,
    batch_id: int,
    object_count: int,
    accepted: bool,
    code: str,
    message: str,
) -> None:
    conn.execute(
        "INSERT INTO close_attempts("
        "batch_id, object_count, threshold, count_mode, accepted, code, message"
        ") VALUES (?,?,?,?,?,?,?)",
        (
            batch_id,
            object_count,
            CLOSE_MIN_OBJECTS,
            COUNT_MODE,
            1 if accepted else 0,
            code,
            message,
        ),
    )


def close_batch(batch_id: int, db_path: str | None = None) -> dict:
    """闭合清单：同一写锁内现场重数 → 门槛校验 → 固化计数。

    空批（现场重数 < 门槛）直接拒收，且拦截原因与计数值落 ``close_attempts``，
    供空批面板 / 解析验收台与本地库核对。
    """
    with get_db(db_path, immediate=True) as conn:
        batch = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404, code="batch_not_found")
        if batch["status"] == "已闭合":
            raise ServiceError("批次已闭合", 409, code="already_closed")
        if batch["status"] != "收集中":
            raise ServiceError("仅收集中批次可闭合", 409, code="not_open")

        # 提交瞬间现场重数（唯一口径）
        n = _count_registered(conn, batch_id)
        gate = evaluate_close_gate(batch["status"], n)
        if not gate["can_close"]:
            # 失败留痕必须先提交，否则回滚会把拦截记录一并抹掉
            _record_attempt(conn, batch_id, n, False, gate["code"], gate["message"])
            conn.commit()
            raise ServiceError(
                gate["message"],
                400,
                code=gate["code"],
                details={
                    "batch_id": batch_id,
                    "object_count": n,
                    "threshold": CLOSE_MIN_OBJECTS,
                    "count_mode": COUNT_MODE,
                    "count_mode_label": COUNT_MODE_LABEL,
                    "chip": gate["chip"],
                },
            )

        conn.execute(
            "UPDATE landing_batches SET status='已闭合', closed_object_count=? WHERE id=?",
            (n, batch_id),
        )
        conn.execute(
            "UPDATE landing_objects SET status='已闭合' WHERE batch_id=? AND status='已登记'",
            (batch_id,),
        )
        _record_attempt(conn, batch_id, n, True, "", f"闭合 {n} 个对象")
        detail = f"闭合 {n} 个对象（口径：{COUNT_MODE_LABEL}）"
        conn.execute(
            "INSERT INTO close_runs(batch_id, object_count, ok, detail) VALUES (?,?,1,?)",
            (batch_id, n, detail),
        )
        run = conn.execute(
            "SELECT * FROM close_runs WHERE batch_id=?", (batch_id,)
        ).fetchone()
        result = dict(run)
        result.update(
            {
                "object_count": n,
                "threshold": CLOSE_MIN_OBJECTS,
                "count_mode": COUNT_MODE,
                "count_mode_label": COUNT_MODE_LABEL,
            }
        )
        return result
