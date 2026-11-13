"""采集结果校验接口：规则维护、版本管理与试运行。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import policy, trial
from app.services.verify import VerifyService

router = APIRouter(prefix="/api/verify", tags=["采集结果校验"])

service = VerifyService()

LIST_FIELDS = ["规则编号", "校验对象", "校验类型", "校验表达式", "阈值配置", "采样比例", "阻断级别", "阻断上限", "当前版本号", "最近校验"]
STATUSES = ["草稿", "运行中", "已暂停", "已归档"]


@router.get("/policy")
def get_policy() -> dict[str, Any]:
    """统一门槛口径：采样阈值、阻断上限、判定标准与越界范围，前后端共用一份。"""
    return policy.policy_spec()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、运行中、已暂停、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤采集结果校验列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/trials/all")
def list_all_trials() -> dict[str, Any]:
    """全量试运行批次，供跨页面追溯最近一次校验批次。"""
    return {"items": trial.list_trials()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集结果校验清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "verify", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条校验规则明细（含版本列表）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"校验规则 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/versions")
def get_versions(entry_id: int) -> dict[str, Any]:
    """规则版本链：试运行结论按批次冻结版本，冲突时以批次启动时冻结版本为准。"""
    versions, message = service.list_versions(entry_id)
    if versions is None:
        raise HTTPException(status_code=404, detail=message)
    return {"rule_id": entry_id, "versions": versions}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条校验规则；不满足统一门槛的配置直接拒绝保存并逐条说明。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="校验规则已登记（版本 v1）", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改规则：越界配置禁止保存；保存成功即生成新版本，旧试运行批次保留原结论。"""
    entry, errors = service.update_entry(entry_id, payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message=f"规则已更新至版本 v{entry['当前版本号']}，新批次按新版本重算", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条校验规则执行启动校验、暂停校验、归档规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/samples/batches")
def sample_batches(plan_id: int | None = Query(default=None, description="可选：只看某采集计划的样本批次")) -> dict[str, Any]:
    """采集计划已落库的结果样本批次，试运行必须从真实批次中选样。"""
    return {"items": trial.list_sample_batches(plan_id)}


@router.post("/{entry_id}/trial")
def run_trial(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对指定采集计划的一个样本批次执行试运行。

    表达式、采样比例、阻断级别全部取自批次启动时冻结的同一版规则；
    同规则同批次重复提交只保留一次结论，不重复阻断。
    """
    plan_id = policy.as_int(payload.values.get("plan_id"))
    batch_no = str(payload.values.get("batch_no") or "").strip()
    if plan_id is None:
        return ActionResult(ok=False, message="缺少 plan_id（采集计划 id）")
    if not batch_no:
        return ActionResult(ok=False, message="缺少 batch_no（样本批次号）")
    result, errors = trial.run_trial(entry_id, plan_id, batch_no)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    reused = bool(result.get("reused"))
    message = "命中相同规则与同批样本，复用既有结论，未重复阻断" if reused else f"试运行完成：{result['verdict']}"
    return ActionResult(ok=True, message=message, entry=result)


@router.get("/{entry_id}/trials")
def list_trials(entry_id: int, plan_id: int | None = None) -> dict[str, Any]:
    """某条规则的试运行批次记录（含冻结版本、判定计数与首批不满足记录）。"""
    return {"items": trial.list_trials(rule_id=entry_id, plan_id=plan_id)}
