"""闭合计数口径与门槛（全局唯一来源）。

计数口径只选一边：**提交瞬间现场重数（live_recount_at_submit）**。
- 点闭合时在同一把写锁内重新统计本批 ``status='已登记'`` 的对象；
- 校验与固化数都使用这一次重数结果；
- 不使用“打开面板时冻结的快照”参与校验，避免两套计数混用。
"""

CLOSE_MIN_OBJECTS = 1
COUNT_MODE = "live_recount_at_submit"
COUNT_MODE_LABEL = "提交瞬间现场重数"

EMPTY_BATCH_CODE = "empty_batch"
EMPTY_MANIFEST_CODE = "empty_manifest"
MANIFEST_MISMATCH_CODE = "manifest_mismatch"
BATCH_NOT_CLOSED_CODE = "batch_not_closed"

CHIP_BLOCKED = "拦截"
CHIP_OK = "可闭合"
CHIP_CLOSED = "已闭合"
CHIP_EMPTY_MANIFEST = "空清单拦截"


def empty_manifest_state(status: str, closed_object_count: int) -> dict | None:
    """已闭合批次若实有清单为空，给出拦截态（供列表/面板/验收台共用）。"""
    if status != "已闭合":
        return None
    n = int(closed_object_count or 0)
    if n > 0:
        return None
    return {
        "can_close": False,
        "code": EMPTY_MANIFEST_CODE,
        "message": (
            f"清单为空：该批已闭合，但实有对象 {n} 个，"
            "解析任务拉清单将被拒收。"
        ),
        "chip": CHIP_EMPTY_MANIFEST,
    }


def evaluate_close_gate(status: str, registered_count: int) -> dict:
    """按现场重数结果给出闭合门槛判定（面板/列表/接口共用）。"""
    n = int(registered_count or 0)
    gate = {
        "object_count": n,
        "threshold": CLOSE_MIN_OBJECTS,
        "count_mode": COUNT_MODE,
        "count_mode_label": COUNT_MODE_LABEL,
        "can_close": False,
        "code": "",
        "message": "",
        "chip": CHIP_BLOCKED,
    }
    if status == "已闭合":
        gate.update(
            code="already_closed",
            message="",
            chip=CHIP_CLOSED,
        )
        return gate
    if status != "收集中":
        gate.update(
            code="not_open",
            message="仅收集中批次可闭合。",
        )
        return gate
    if n < CLOSE_MIN_OBJECTS:
        gate.update(
            code=EMPTY_BATCH_CODE,
            message=(
                f"空批不能闭合：本批实有对象 {n} 个，"
                f"门槛要求至少 {CLOSE_MIN_OBJECTS} 个（口径：{COUNT_MODE_LABEL}）。"
            ),
        )
        return gate
    gate.update(can_close=True, chip=CHIP_OK)
    return gate
