"""区间申请接口：旧导出时段迁移、领取进度详情、片段领取与签收。

注意固定路径（migrate / legacy / deploy-switch）必须注册在 /{claim_id} 之前，
否则会被动态路径抢先匹配。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.interval_claim import ENTRY_INTERVAL, interval_claim_service

router = APIRouter(prefix="/api/interval-claims", tags=["区间申请"])


class OpenPayload(BaseModel):
    start: str = Field(..., description="开始时刻（带时区偏移）")
    end: str = Field(..., description="结束时刻（带时区偏移）")
    source_module: str = Field(default="batch_export", description="来源模块")
    fragment_minutes: int = Field(default=60, description="片段粒度（分钟）")
    entry: str = Field(default=ENTRY_INTERVAL, description="打开入口")


class MigratePayload(BaseModel):
    module: str = Field(..., description="旧记录所在模块：batch_export / data_stream")
    record_id: str = Field(..., description="旧记录 id 或编号")
    entry: str = Field(default=ENTRY_INTERVAL, description="迁移入口")
    fragment_minutes: int = Field(default=180, description="片段粒度（分钟）")


class ClaimPayload(BaseModel):
    entry: str = Field(..., description="领取入口")
    token: str = Field(default="", description="续领凭证")


class SignPayload(BaseModel):
    entry: str = Field(..., description="签收入口")
    token: str = Field(default="", description="续领凭证")
    seq: int = Field(..., description="片段序号")


@router.get("")
def list_requests():
    """区间申请列表。"""
    return interval_claim_service.list_requests()


@router.post("")
def open_request(payload: OpenPayload):
    """打开一笔新的区间申请。"""
    return interval_claim_service.open_request(
        start_text=payload.start,
        end_text=payload.end,
        source_module=payload.source_module,
        fragment_minutes=payload.fragment_minutes,
        entry=payload.entry,
    )


@router.post("/migrate")
def migrate_legacy(payload: MigratePayload):
    """把一条旧导出记录迁移成区间申请。"""
    return interval_claim_service.migrate_legacy(
        module=payload.module,
        record_id=payload.record_id,
        entry=payload.entry,
        fragment_minutes=payload.fragment_minutes,
    )


@router.get("/legacy/{module}/{record_id}")
def inspect_legacy(module: str, record_id: str):
    """核对一条旧导出记录：可解释的给出真实区间，不可解释的保留原文和原因。"""
    return interval_claim_service.inspect_legacy(module, record_id)


@router.post("/deploy-switch")
def deploy_switch():
    """模拟部署切换：回收处理中片段、作废续领凭证，已签收进度保留。"""
    return interval_claim_service.deploy_switch()


@router.get("/{claim_id}")
def progress_detail(claim_id: str):
    """领取进度详情：历史时区、实际区间、掌管入口、片段状态和续领凭证。"""
    return interval_claim_service.progress_detail(claim_id)


@router.post("/{claim_id}/claim-next")
def claim_next(claim_id: str, payload: ClaimPayload):
    """领取下一个待领取片段。"""
    return interval_claim_service.claim_next(claim_id, payload.entry, payload.token)


@router.post("/{claim_id}/sign")
def sign_fragment(claim_id: str, payload: SignPayload):
    """签收片段：已确认的片段不会再次交付。"""
    return interval_claim_service.sign_fragment(claim_id, payload.entry, payload.token, payload.seq)
