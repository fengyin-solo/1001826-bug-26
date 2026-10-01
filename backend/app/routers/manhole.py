"""检查井接口：登记覆盖、状态流转、归属调整、统计与催办清单。

只读岗位（viewer）只能看，登记、确认、废弃、调整归属等写操作一律拒绝。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.manhole import (
    ACTION_RULES,
    BUSINESS_FIELDS,
    OWNERSHIP_FIELD,
    STATUS_ORDER,
    ManholeService,
)

router = APIRouter(prefix="/api/manhole", tags=["检查井"])

service = ManholeService()

LIST_FIELDS = BUSINESS_FIELDS
STATUSES = STATUS_ORDER
ACTIONS = list(ACTION_RULES)

# 可执行写操作的岗位；只读岗位不在其列。
WRITABLE_ROLES = {"admin", "operator", "editor"}
ROLE_NAMES = {"admin": "管理员", "operator": "值班操作员", "editor": "维护人员", "viewer": "只读查看员"}


def _require_write(x_role: str | None) -> str:
    role = (x_role or "operator").strip().lower()
    if role not in WRITABLE_ROLES:
        name = ROLE_NAMES.get(role, role)
        raise HTTPException(status_code=403, detail=f"当前岗位「{name}」为只读权限，不能改动检查井归属与状态")
    return role


def _filters(
    keyword: str | None,
    road: str | None,
    cover: str | None,
    status: str | None,
    key_only: bool,
    urgent_only: bool,
) -> dict[str, Any]:
    return {
        "keyword": (keyword or "").strip() or None,
        "road": (road or "").strip() or None,
        "cover": (cover or "").strip() or None,
        "status": (status or "").strip() or None,
        "key_only": key_only,
        "urgent_only": urgent_only,
    }


# 具体路径放在 /{entry_id} 之前，避免 export、stats 当成井编号解析。
@router.get("/export")
def export_entries(
    keyword: str | None = None,
    road: str | None = None,
    cover: str | None = None,
    status: str | None = None,
    key_only: bool = False,
    urgent_only: bool = False,
) -> dict[str, Any]:
    """导出检查井清单：按当前筛选条件返回全量数据。"""
    items, total = service.list_entries(
        **_filters(keyword, road, cover, status, key_only, urgent_only),
        page=1,
        size=10000,
    )
    return {"module": "manhole", "total": total, "items": items}


@router.get("/stats")
def get_stats(
    keyword: str | None = None,
    road: str | None = None,
    cover: str | None = None,
    status: str | None = None,
    key_only: bool = False,
    urgent_only: bool = False,
) -> dict[str, Any]:
    """统计卡片：与列表共用筛选口径，筛出多少条就按多少条算。"""
    return {"items": service.stats(**_filters(keyword, road, cover, status, key_only, urgent_only))}


@router.get("/reminders")
def list_reminders(
    keyword: str | None = Query(default=None, description="按井编号检索"),
    road: str | None = Query(default=None, description="按所在道路检索"),
    cover: str | None = Query(default=None, description="按井盖类别检索"),
) -> dict[str, Any]:
    """催办清单：井盖缺失、超限值重点清掏、待清掏的井都落到这里。"""
    items, total = service.list_reminders(keyword=keyword, road=road, cover=cover)
    return {"total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按井编号检索"),
    road: str | None = Query(default=None, description="按所在道路检索"),
    cover: str | None = Query(default=None, description="按井盖类别检索"),
    status: str | None = Query(default=None, description="待清掏、正常使用、井盖缺失、已废弃"),
    key_only: bool = Query(default=False, description="只看超限值的重点清掏井"),
    urgent_only: bool = Query(default=False, description="只看需要催办的井"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按井编号、道路、井盖类别与状态过滤检查井列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        **_filters(keyword, road, cover, status, key_only, urgent_only), page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检查井明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检查井 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, x_role: str | None = Header(default=None)) -> ActionResult:
    """登记检查井：同井编号后到一份覆盖旧值并留档；缺字段时说明原因而不是静默丢弃。"""
    _require_write(x_role)
    entry, missing, created = service.upsert_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    message = "检查井已登记" if created else f"检查井{entry['井编号']}已有更新，后到数据已覆盖，旧取值已留版"
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int, payload: EntryPayload, x_role: str | None = Header(default=None)
) -> ActionResult:
    """对单条检查井执行安排清掏、确认正常、上报缺失、废弃井室。"""
    _require_write(x_role)
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/ownership", response_model=ActionResult)
def change_ownership(
    entry_id: int, payload: EntryPayload, x_role: str | None = Header(default=None)
) -> ActionResult:
    """调整检查井归属（责任班组）；只读岗位调用会被 403 拦下。"""
    _require_write(x_role)
    owner = str(payload.values.get(OWNERSHIP_FIELD) or "").strip()
    entry, message = service.change_ownership(entry_id, owner)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
