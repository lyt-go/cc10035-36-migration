"""区间申请场景测试：旧导出时段迁移、跨时区计费、隔天续领与入口冲突。

对应业务场景：
1. 打开跨时区两小时作业，账单每小时 0.05 元；
2. 管道的「过去一天」旧任务以当天 16:30 为截止，锚定原提交时间；
3. 前半程四条签收后，遇到部署切换和领取冲突、浏览器丢了答复；
4. 第二天从进度页续领：已签仍是四条、补领不超过 16:30、掌管入口可见；
5. 格式不明的旧记录保留原文本和不可继续的原因。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import interval_claim as ic
from app.services.interval_claim import (
    ENTRY_INTERVAL,
    ENTRY_LEGACY,
    IntervalClaimService,
)
from app.store import store

CST = timezone(timedelta(hours=8))


@pytest.fixture
def service():
    store.rows("interval_claim").clear()
    ic._DEPLOY_EPOCH = 1
    return IntervalClaimService()


def _claim_and_sign(service: IntervalClaimService, claim_id: str, entry: str, token: str) -> str:
    """领取并签收一个片段，返回最新的续领凭证。"""
    claim = service.claim_next(claim_id, entry, token)
    assert claim["ok"], claim
    assert "fragment" in claim
    signed = service.sign_fragment(claim_id, entry, claim["续领凭证"], claim["fragment"]["seq"])
    assert signed["ok"], signed
    return signed["续领凭证"]


# ---------- 场景一：跨时区两小时作业的账单 ----------

def test_cross_timezone_two_hour_job_billing(service):
    result = service.open_request(
        start_text="2026-11-26T08:00:00+08:00",
        end_text="2026-11-26T02:00:00+00:00",
        fragment_minutes=60,
    )
    assert result["ok"], result
    req = result["request"]
    assert req["跨时区"] is True
    assert req["区间开始UTC"] == "2026-11-26T00:00:00+00:00"
    assert req["区间结束UTC"] == "2026-11-26T02:00:00+00:00"
    assert req["时长小时"] == 2.0
    assert req["费用单价元每小时"] == 0.05
    assert req["费用估算元"] == 0.1  # 两小时 × 每小时 0.05 元
    assert req["片段总数"] == 2


def test_open_request_requires_offset_and_order(service):
    missing_offset = service.open_request("2026-11-26 08:00:00", "2026-11-26 10:00:00")
    assert missing_offset["ok"] is False

    reversed_range = service.open_request(
        "2026-11-26T10:00:00+08:00", "2026-11-26T08:00:00+08:00"
    )
    assert reversed_range["ok"] is False


# ---------- 场景二：旧记录迁移 ----------

def test_migrate_pipeline_past_day_anchors_submit_time(service):
    result = service.migrate_legacy("data_stream", "DATA-0004", fragment_minutes=180)
    assert result["ok"], result
    req = result["request"]
    assert req["时段类型"] == "past_day"
    assert req["历史时区"] == "UTC+08:00"
    # 过去一天锚定原提交时间，截止当天 16:30
    assert req["区间开始"] == "2026-11-25T16:30:00+08:00"
    assert req["区间结束"] == "2026-11-26T16:30:00+08:00"
    assert req["片段总数"] == 8
    assert req["费用估算元"] == 1.2  # 24 小时 × 0.05 元


def test_explicit_offset_legacy_keeps_actual_interval(service):
    result = service.migrate_legacy("batch_export", "BATC-0005")
    assert result["ok"], result
    req = result["request"]
    assert req["时段类型"] == "explicit"
    assert req["区间开始UTC"] == "2026-11-20T00:30:00+00:00"
    assert req["区间结束UTC"] == "2026-11-20T04:45:00+00:00"
    assert req["跨时区"] is True
    assert req["时长小时"] == 4.25
    assert req["费用估算元"] == round(4.25 * 0.05, 4)


def test_migrate_is_idempotent(service):
    first = service.migrate_legacy("data_stream", "DATA-0004")
    second = service.migrate_legacy("data_stream", "DATA-0004")
    assert first["ok"] and second["ok"]
    assert second["already"] is True
    assert second["request"]["申请编号"] == first["request"]["申请编号"]
    assert len(store.rows("interval_claim")) == 1


def test_unparseable_legacy_keeps_raw_text_and_reason(service):
    inspected = service.inspect_legacy("batch_export", "BATC-0006")
    assert inspected["ok"]
    assert inspected["可继续"] is False
    assert inspected["原文本"] == "上月下旬到现在的老数据"
    assert inspected["失败原因"]

    migrated = service.migrate_legacy("batch_export", "BATC-0006")
    assert migrated["ok"] is False
    assert migrated["code"] == "UNRESOLVABLE_PERIOD"
    assert migrated["原文本"] == "上月下旬到现在的老数据"
    assert migrated["失败原因"]


def test_past_day_without_submit_time_unresolvable():
    resolution = ic.resolve_legacy_period({"时间范围": "过去一天"})
    assert resolution["resolvable"] is False
    assert "提交时间" in resolution["失败原因"]


# ---------- 场景三：隔天续领（部署切换 + 领取冲突 + 丢失答复） ----------

def test_continue_next_day_after_deploy_switch_and_conflict(service, monkeypatch):
    # 迁移管道的过去一天任务（旧记录以当天 16:30 为截止）
    migrated = service.migrate_legacy("data_stream", "DATA-0004", fragment_minutes=180)
    claim_id = migrated["request"]["申请编号"]
    detail = service.progress_detail(claim_id)
    assert detail["掌管入口"] == ENTRY_INTERVAL
    token = detail["续领凭证"]

    # 前半程：四条签收
    for _ in range(4):
        token = _claim_and_sign(service, claim_id, ENTRY_INTERVAL, token)
    half = service.progress_detail(claim_id)
    assert half["已签收数"] == 4
    signed_marks = {f["seq"]: f["签收时间"] for f in half["fragments"] if f["state"] == "已签收"}
    assert len(signed_marks) == 4

    # 下一片段处理期间：旧入口并行续领 → 领取冲突，能看清掌管入口
    token = service.claim_next(claim_id, ENTRY_INTERVAL, token)["续领凭证"]
    conflict = service.claim_next(claim_id, ENTRY_LEGACY, token)
    assert conflict["ok"] is False
    assert conflict["code"] == "ENTRY_CONFLICT"
    assert conflict["掌管入口"] == ENTRY_INTERVAL

    # 部署切换：处理中片段回收、续领凭证作废（浏览器丢了答复也不影响服务端进度）
    switched = service.deploy_switch()
    assert switched["回收处理中片段"] == 1
    stale = service.claim_next(claim_id, ENTRY_INTERVAL, token)
    assert stale["ok"] is False
    assert stale["code"] == "STALE_PROGRESS"

    # 第二天：从进度页核对历史时区和实际区间后续领
    next_day = datetime(2026, 11, 27, 9, 0, tzinfo=CST)
    monkeypatch.setattr(ic, "_now_dt", lambda: next_day)

    resumed = service.progress_detail(claim_id)
    assert resumed["已签收数"] == 4  # 已签部分仍是四条
    assert resumed["掌管入口"] == ENTRY_INTERVAL  # 能看清哪个入口掌管这个申请
    assert resumed["历史时区"] == "UTC+08:00"
    assert resumed["实际区间"]["结束"] == "2026-11-26T16:30:00+08:00"

    token = resumed["续领凭证"]
    delivered = []
    while True:
        claim = service.claim_next(claim_id, ENTRY_INTERVAL, token)
        assert claim["ok"], claim
        if claim.get("done"):
            break
        delivered.append(claim["fragment"])
        token = service.sign_fragment(
            claim_id, ENTRY_INTERVAL, claim["续领凭证"], claim["fragment"]["seq"]
        )["续领凭证"]

    # 实际补领不超过原来的 16:30，不因隔天操作重新按当前时间取数
    assert len(delivered) == 4
    cutoff = datetime.fromisoformat("2026-11-26T16:30:00+08:00")
    for frag in delivered:
        assert datetime.fromisoformat(frag["结束"]) <= cutoff
    assert delivered[-1]["结束"] == "2026-11-26T16:30:00+08:00"

    final = service.progress_detail(claim_id)
    assert final["已签收数"] == 8
    assert final["状态"] == "已完成"
    # 前半程四条签收时间未被改写：已确认的片段没有再次交付
    for frag in final["fragments"][:4]:
        assert frag["签收时间"] == signed_marks[frag["seq"]]
    # 估算费用以同次申请的真实区间为准
    assert final["费用"]["估算元"] == 1.2
    assert final["实际区间"]["开始"] == "2026-11-25T16:30:00+08:00"


# ---------- 领取/签收的基础规则 ----------

def test_only_owner_entry_continues(service):
    migrated = service.migrate_legacy("batch_export", "BATC-0004", entry=ENTRY_LEGACY)
    claim_id = migrated["request"]["申请编号"]
    detail = service.progress_detail(claim_id)
    assert detail["掌管入口"] == ENTRY_LEGACY

    # 新入口即使拿到凭证，不是掌管入口也接续不了
    blocked = service.claim_next(claim_id, ENTRY_INTERVAL, detail["续领凭证"])
    assert blocked["ok"] is False
    assert blocked["code"] == "ENTRY_CONFLICT"
    assert blocked["掌管入口"] == ENTRY_LEGACY

    # 掌管入口正常接续
    claim = service.claim_next(claim_id, ENTRY_LEGACY, detail["续领凭证"])
    assert claim["ok"], claim


def test_in_flight_fragment_redelivered_to_same_entry(service):
    opened = service.open_request(
        "2026-11-26T08:00:00+08:00", "2026-11-26T10:00:00+08:00", fragment_minutes=60
    )
    claim_id = opened["request"]["申请编号"]
    first = service.claim_next(claim_id, ENTRY_INTERVAL, opened["续领凭证"])
    assert first["ok"]

    # 浏览器丢了答复，凭进度详情重新核对后重领：同一片段重新交付，不跳过
    detail = service.progress_detail(claim_id)
    retry = service.claim_next(claim_id, ENTRY_INTERVAL, detail["续领凭证"])
    assert retry["ok"]
    assert retry["redelivered"] is True
    assert retry["fragment"]["seq"] == first["fragment"]["seq"]


def test_signed_fragment_never_redelivered(service):
    opened = service.open_request(
        "2026-11-26T08:00:00+08:00", "2026-11-26T10:00:00+08:00", fragment_minutes=60
    )
    claim_id = opened["request"]["申请编号"]
    token = _claim_and_sign(service, claim_id, ENTRY_INTERVAL, opened["续领凭证"])

    # 重复签收幂等返回，不重复交付
    again = service.sign_fragment(claim_id, ENTRY_INTERVAL, token, 1)
    assert again["ok"]
    assert again["already_signed"] is True

    # 下一次领取只能拿到片段 2，已签收的片段 1 不再交付
    nxt = service.claim_next(claim_id, ENTRY_INTERVAL, token)
    assert nxt["ok"]
    assert nxt["fragment"]["seq"] == 2

    token = _claim_and_sign(service, claim_id, ENTRY_INTERVAL, nxt["续领凭证"])
    done = service.claim_next(claim_id, ENTRY_INTERVAL, token)
    assert done["ok"] and done["done"] is True
    assert done["已签收数"] == 2
