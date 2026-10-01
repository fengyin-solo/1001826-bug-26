"""检查井接口：维护检查井，覆盖安排清掏、确认正常、上报缺失、废弃井室等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.manhole import (
    ManholePermissionError,
    ManholeService,
)

router = APIRouter(prefix="/api/manhole", tags=["检查井"])

service = ManholeService()

LIST_FIELDS = ["井编号", "所在道路", "井盖类别", "井室深度", "井室尺寸", "上次清掏日", "责任班组", "检查井状态"]
STATUSES = ["待清掏", "正常使用", "井盖缺失", "已废弃"]


def _parse_flag(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value in {"1", "true", "True", "yes", "重点"}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按井编号检索"),
    status: str | None = Query(default=None, description="待清掏、正常使用、井盖缺失、已废弃"),
    only_key: str | None = Query(default=None, description="传 1/true 只看重点清掏井"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按井编号、状态、重点清掏过滤检查井列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        only_key=_parse_flag(only_key),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def manhole_stats() -> dict[str, int]:
    """统计口径与列表筛选共用：重点检查井数量与重点清掏筛选条数一致。"""
    return service.stats()


@router.get("/urgings")
def manhole_urgings() -> dict[str, Any]:
    """催办清单：待清掏与井盖缺失的结论实时落单，条数随结论重算。"""
    items, total = service.urgings()
    return {"items": items, "total": total}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检查井清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "manhole", "total": total, "items": items}


@router.post("", response_model=ActionResult, status_code=200)
def create_entry(
    payload: EntryPayload,
    x_operator_role: str | None = Header(default=None),
) -> ActionResult:
    """登记或重新上报检查井：同井编号后到的一份覆盖，缺字段时说明原因。"""
    try:
        entry, message = service.submit_entry(payload.values, role=x_operator_role)
    except ManholePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检查井明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检查井 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检查井执行安排清掏、确认正常、上报缺失、废弃井室；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
