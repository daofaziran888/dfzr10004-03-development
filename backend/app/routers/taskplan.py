"""采集任务编排接口：计划维护、校验待处理清单与下一批抓取门禁。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import trial
from app.services.taskplan import TaskplanService

router = APIRouter(prefix="/api/taskplan", tags=["采集任务编排"])

service = TaskplanService()

LIST_FIELDS = ["计划编号", "目标站点", "采集频率", "数据范围", "优先级", "资源配额", "预计用时", "计划状态"]
STATUSES = ["草稿", "运行中", "已暂停", "已完成"]


@router.get("/guards/pending")
def all_pending_guards() -> dict[str, Any]:
    """采集计划页的待处理清单：跨计划汇总最近一次校验批次与阻断原因。"""
    return {"items": trial.list_guards(only_open=True)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="草稿、运行中、已暂停、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤采集任务编排列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}/guard")
def guard_overview(entry_id: int) -> dict[str, Any]:
    """单个计划的校验看板：最近一次校验批次、阻断原因、硬阻断/警告数量与下一批门禁。"""
    overview, message = service.guard_overview(entry_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=message)
    return overview


@router.post("/{entry_id}/next-batch")
def next_batch(entry_id: int) -> ActionResult:
    """进入下一批抓取的统一门禁：硬阻断拦截，仅警告放行并保留待处理项。"""
    entry, message, allowed = service.request_next_batch(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=allowed, message=message, entry=entry)


@router.post("/guards/{guard_id}/resolve")
def resolve_guard(guard_id: int) -> ActionResult:
    """处理一条待办项：硬阻断解除后计划才能进入下一批；重复处理幂等。"""
    guard, message = trial.resolve_guard(guard_id)
    if guard is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=guard)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条采集计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"采集计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条采集计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集计划已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条采集计划执行启动计划、暂停计划、归档计划；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集任务编排清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "taskplan", "total": total, "items": items}
