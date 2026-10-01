"""检查井业务规则：状态流转、字段校验与筛选口径都收在这里。

口径约定（列表、详情、统计、催办清单全部以这里为准）：
- 规范状态只有一个：``status``；「检查井状态」展示字段始终与它保持同步，
  列表和详情读的是同一份数据，不会再出现两套结果。
- 井室深度超过 ``DEPTH_LIMIT_M``（按米计）的井自动打上 ``重点清掏`` 标记，
  统计里的「重点检查井」与列表按重点清掏筛出来的条数走同一套判定。
- 状态为「待清掏」「井盖缺失」的井都会落到催办清单，清单每次实时重算。
- 同一井编号重复上报按后到的一份覆盖，不堆积新记录；覆盖前的取值快照
  留在 ``history`` 里，旧值照当时那版保留。
- 只读岗位（``READONLY_ROLES``）不能调整检查井归属（责任班组）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.store import store

MODULE = "manhole"

# 可登记/可上报的字段
EDITABLE_FIELDS = ["井编号", "所在道路", "井盖类别", "井室深度", "井室尺寸", "上次清掏日", "责任班组"]
REQUIRED_FIELDS = ["井编号", "所在道路", "井盖类别"]

STATUS_PENDING = "待清掏"
STATUS_NORMAL = "正常使用"
STATUS_MISSING = "井盖缺失"
STATUS_DISCARDED = "已废弃"
STATUS_ORDER = [STATUS_PENDING, STATUS_NORMAL, STATUS_MISSING, STATUS_DISCARDED]

# 动作到规范状态的判定口径：确认正常就是正常使用；井盖缺失由专门的上报动作给出
ACTION_RULES = {
    "安排清掏": STATUS_PENDING,
    "确认正常": STATUS_NORMAL,
    "上报缺失": STATUS_MISSING,
    "废弃井室": STATUS_DISCARDED,
}
# 需要继续跟进的状态；井盖缺失同时计为异常
PENDING_STATUSES = {STATUS_PENDING, STATUS_MISSING}
ABNORMAL_STATUSES = {STATUS_MISSING}
# 终态：废弃后不再接受任何动作
FINAL_STATUSES = {STATUS_DISCARDED}

# 井室深度限值（米）：超过即按口径自动归入重点清掏
DEPTH_LIMIT_M = 3.0

# 催办清单的判定口径
URGING_STATUS_LABELS = {
    STATUS_PENDING: "安排清掏",
    STATUS_MISSING: "补装井盖",
}

# 只读岗位：可以看、可以上报现场情况，但不能动检查井归属
READONLY_ROLES = {"只读员", "viewer", "readonly"}


class ManholePermissionError(PermissionError):
    """只读岗位触碰了归属等只读红线时抛出，路由层映射为 403。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_depth(value: Any) -> float | None:
    """把「3.2 米」「3.2m」这类取值解析成米；解析不了返回 None，不做归类。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("米", "").replace("m", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_key_dredging(entry: dict[str, Any]) -> bool:
    """井室深度超过限值的井按口径进入重点清掏。"""
    depth = parse_depth(entry.get("井室深度"))
    return depth is not None and depth > DEPTH_LIMIT_M


def _snapshot(entry: dict[str, Any], source: str) -> dict[str, Any]:
    """留下一版当时的取值，后续覆盖不影响已经归档的旧版。"""
    snap = {
        "time": _now(),
        "来源": source,
        "状态": entry.get("status"),
        "重点清掏": bool(entry.get("重点清掏")),
    }
    for field in EDITABLE_FIELDS:
        snap[field] = entry.get(field)
    return snap


def _recompute(entry: dict[str, Any]) -> None:
    """按当前取值重算派生标记，保证 status / 展示字段 / 重点清掏 / 催办口径一致。"""
    status = entry.get("status") if entry.get("status") in STATUS_ORDER else STATUS_PENDING
    entry["status"] = status
    entry["检查井状态"] = status
    entry["重点清掏"] = is_key_dredging(entry)
    entry["pending"] = status in PENDING_STATUSES
    entry["abnormal"] = status in ABNORMAL_STATUSES


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """把历史/示例数据对齐到当前口径（只补不改业务取值）。"""
    _recompute(entry)
    entry.setdefault("history", [])
    return entry


def _matches(
    row: dict[str, Any],
    *,
    keyword: str | None = None,
    status: str | None = None,
    only_key: bool | None = None,
) -> bool:
    """列表筛选与统计共用同一套口径，筛出来的条数和统计数天然对得上。"""
    if keyword and keyword not in str(row.get("井编号", "")):
        return False
    if status and row.get("status") != status:
        return False
    if only_key is not None and bool(row.get("重点清掏")) != only_key:
        return False
    return True


class ManholeService:
    def __init__(self) -> None:
        # 启动即把示例数据对齐到当前口径，刷新前后看到的状态保持一致
        for row in store.rows(MODULE):
            normalize_entry(row)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        only_key: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [
            row
            for row in store.rows(MODULE)
            if _matches(row, keyword=keyword, status=status, only_key=only_key)
        ]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> dict[str, int]:
        """统计口径直接复用列表判定，重点检查井数量 = 重点清掏筛选条数。"""
        rows = store.rows(MODULE)
        return {
            "在册检查井": len(rows),
            "待清掏井室": sum(1 for row in rows if row.get("status") == STATUS_PENDING),
            "井盖缺失": sum(1 for row in rows if row.get("status") == STATUS_MISSING),
            "重点检查井": sum(1 for row in rows if _matches(row, only_key=True)),
            "催办清单": sum(1 for row in rows if row.get("status") in URGING_STATUS_LABELS),
        }

    def urgings(self) -> tuple[list[dict[str, Any]], int]:
        """检查井结论落到催办清单；每次实时重算，条数跟着结论走。"""
        items = [
            {
                "检查井id": row.get("id"),
                "井编号": row.get("井编号"),
                "所在道路": row.get("所在道路"),
                "责任班组": row.get("责任班组"),
                "催办事项": URGING_STATUS_LABELS[row["status"]],
                "检查井状态": row.get("检查井状态", row.get("status")),
                "重点清掏": bool(row.get("重点清掏")),
            }
            for row in store.rows(MODULE)
            if row.get("status") in URGING_STATUS_LABELS
        ]
        return items, len(items)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return normalize_entry(entry) if entry is not None else None

    def find_by_code(self, well_code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("井编号", "")).strip() == well_code:
                return row
        return None

    def submit_entry(self, values: dict[str, Any], role: str | None = None) -> tuple[dict[str, Any], str]:
        """登记或重新上报一口井。

        同一井编号只保留一份，后到的一份覆盖旧值（不堆积）；覆盖前先把旧版
        取值存入 history，旧值照当时那版留着。只读岗位改不动责任班组（归属）。
        """
        well_code = str(values.get("井编号") or "").strip()
        existing = self.find_by_code(well_code) if well_code else None

        if existing is not None:
            new_team = values.get("责任班组")
            if (
                role in READONLY_ROLES
                and new_team is not None
                and str(new_team).strip() != str(existing.get("责任班组") or "").strip()
            ):
                raise ManholePermissionError("只读岗位无权调整检查井归属（责任班组）")
            if existing.get("status") in FINAL_STATUSES:
                return existing, "检查井已废弃，重新上报不再覆盖，请先恢复状态"
            history = existing.setdefault("history", [])
            history.append(_snapshot(existing, "重新上报"))
            entry = existing
            for field in EDITABLE_FIELDS:
                if field in values and field != "井编号":
                    entry[field] = values.get(field)
            message = "检查井已按最新上报覆盖"
        else:
            missing = [
                field
                for field in REQUIRED_FIELDS
                if not str(values.get(field) or "").strip()
            ]
            if missing:
                raise ValueError(f"缺少必填字段：{'、'.join(missing)}")
            if role in READONLY_ROLES:
                raise ManholePermissionError("只读岗位无权登记新的检查井归属")
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in EDITABLE_FIELDS:
                entry[field] = values.get(field)
            entry["status"] = STATUS_PENDING
            entry["history"] = []
            rows.append(entry)
            message = "检查井已登记"

        _recompute(entry)
        return entry, message

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检查井 {entry_id} 不存在或已归档"
        normalize_entry(entry)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检查井可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry["status"] in FINAL_STATUSES:
            return None, "检查井已废弃，不能再执行状态动作"
        # 重复确认/重复上报原样保留结果：不再覆盖、不追加历史，结果不会被改回去
        if entry["status"] == target:
            return entry, f"检查井已是「{target}」，结果保持不变"
        entry.setdefault("history", []).append(_snapshot(entry, action))
        entry["status"] = target
        _recompute(entry)
        return entry, f"检查井已{action}"
