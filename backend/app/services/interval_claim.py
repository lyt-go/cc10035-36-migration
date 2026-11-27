"""区间申请领域服务：旧导出时段向区间申请的迁移与片段领取管理。

数据流管道和批量导出两套模块里存在两套旧导出时段格式：
- 「过去一天」：锚定在原提交时间，截止时刻固定，不随操作日变化；
- 带偏移的明确时刻：保留实际区间；
- 无法解释的数据：展示原值和失败原因，不允许继续。

迁移后统一为区间申请：
- 操作人先从领取进度详情核对历史时区和实际当时申请的区间，再继续没拿到的片段；
- 新旧入口并行时，一笔原申请只由持有有效进度依据（掌管入口 + 续领凭证）的入口接续；
- 已签收片段不会再次交付；
- 估算费用和交付片段以同次申请的真实区间为准（0.05 元/小时），
  不因隔天操作而重新按当前时间取数。
"""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.store import store

CST = timezone(timedelta(hours=8))

# 费用单价：每小时 0.05 元
RATE_PER_HOUR = 0.05

# 新旧两个并行入口
ENTRY_INTERVAL = "区间申请入口"
ENTRY_LEGACY = "旧导出入口"
ENTRIES = (ENTRY_INTERVAL, ENTRY_LEGACY)

# 区间申请来源模块（两套旧导出时段所在的模块）
LEGACY_MODULES = ("batch_export", "data_stream")

# 「过去一天」类口径的别名
PAST_DAY_ALIASES = {"过去一天", "前一天", "昨日", "过去24小时", "last_day", "past_day"}

# 带时区偏移的明确时刻，如 2026-11-20T08:30:00+08:00 / 2026-11-20 04:45:00Z
_MOMENT_WITH_OFFSET_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:Z|z|[+-]\d{2}:?\d{2})"
)
# 没有任何偏移信息的时刻（用于给出更明确的失败原因）
_MOMENT_PLAIN_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

# 片段状态
STATE_PENDING = "待领取"
STATE_CLAIMED = "处理中"
STATE_SIGNED = "已签收"

# 部署轮次：部署切换会回收处理中片段并作废续领凭证
_DEPLOY_EPOCH = 1


def _now_dt() -> datetime:
    return datetime.now(CST)


def _now() -> str:
    return _now_dt().isoformat(timespec="seconds")


def _parse_moment(text: str) -> datetime | None:
    """把带偏移的时刻文本解析成 aware datetime；解析不了返回 None。"""
    value = (text or "").strip()
    if not value:
        return None
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment


def _tz_label(moment: datetime) -> str:
    offset = moment.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def resolve_legacy_period(record: dict[str, Any]) -> dict[str, Any]:
    """把一条旧导出记录解释成真实区间。

    返回可继续时包含 start/end（aware datetime）；不可继续时包含原文本和失败原因。
    """
    raw = str(record.get("导出时段") or record.get("时间范围") or "").strip()
    submitted_raw = str(record.get("提交时间") or "").strip()

    if not raw:
        return {"resolvable": False, "原文本": "", "失败原因": "记录里没有时段字段，无法确定申请区间"}

    if raw in PAST_DAY_ALIASES:
        anchor = _parse_moment(submitted_raw)
        if anchor is None:
            return {
                "resolvable": False,
                "原文本": raw,
                "失败原因": f"「{raw}」需要锚定原提交时间，但提交时间「{submitted_raw or '空'}」无法解释",
            }
        # 过去一天：锚定在原提交时间，截止即提交时刻，不随操作日变化
        return {
            "resolvable": True,
            "kind": "past_day",
            "start": anchor - timedelta(hours=24),
            "end": anchor,
            "anchor": anchor,
            "原文本": raw,
        }

    moments = [_parse_moment(m.group(0)) for m in _MOMENT_WITH_OFFSET_RE.finditer(raw)]
    moments = [m for m in moments if m is not None]
    if len(moments) >= 2:
        start, end = moments[0], moments[1]
        if end <= start:
            return {
                "resolvable": False,
                "原文本": raw,
                "失败原因": "明确时刻的结束不晚于开始，无法构成有效区间",
            }
        # 带偏移的明确时刻：保留实际区间
        return {"resolvable": True, "kind": "explicit", "start": start, "end": end, "原文本": raw}

    if _MOMENT_PLAIN_RE.search(raw):
        return {
            "resolvable": False,
            "原文本": raw,
            "失败原因": "时刻缺少时区偏移，无法确定实际区间",
        }
    return {
        "resolvable": False,
        "原文本": raw,
        "失败原因": "既非「过去一天」类口径，也不含带偏移的明确时刻，无法解释",
    }


class IntervalClaimService:
    """区间申请与片段领取的领域服务。"""

    TABLE = "interval_claim"

    # ---------- 基础查询 ----------

    def _rows(self) -> list[dict[str, Any]]:
        return store.rows(self.TABLE)

    def _find(self, claim_id: str) -> dict[str, Any] | None:
        key = str(claim_id).strip()
        for row in self._rows():
            if row.get("申请编号") == key:
                return row
        if key.isdigit():
            for row in self._rows():
                if int(row.get("id", 0)) == int(key):
                    return row
        return None

    @staticmethod
    def _find_legacy_record(module: str, record_id: str) -> dict[str, Any] | None:
        key = str(record_id).strip()
        code_field = {"batch_export": "任务编号", "data_stream": "管道编号"}.get(module, "")
        for row in store.rows(module):
            if key.isdigit() and int(row.get("id", 0)) == int(key):
                return row
            if code_field and row.get(code_field) == key:
                return row
        return None

    # ---------- 建单 ----------

    def _build_request(
        self,
        *,
        kind: str,
        source_module: str,
        source_record: str,
        start: datetime,
        end: datetime,
        fragment_minutes: int,
        entry: str,
        submitted_at: str = "",
        legacy_text: str = "",
    ) -> dict[str, Any]:
        rows = self._rows()
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        total_seconds = (end - start).total_seconds()
        hours = round(total_seconds / 3600, 4)
        fragment_seconds = fragment_minutes * 60
        count = max(1, math.ceil(total_seconds / fragment_seconds))

        fragments: list[dict[str, Any]] = []
        for seq in range(1, count + 1):
            frag_start = start + timedelta(seconds=fragment_seconds * (seq - 1))
            # 最后一片严格收在区间结束，交付永远不越过原申请截止
            frag_end = min(start + timedelta(seconds=fragment_seconds * seq), end)
            fragments.append({
                "seq": seq,
                "开始": _iso(frag_start),
                "结束": _iso(frag_end),
                "开始UTC": _iso_utc(frag_start),
                "结束UTC": _iso_utc(frag_end),
                "state": STATE_PENDING,
                "领取入口": "",
                "领取时间": "",
                "签收时间": "",
            })

        request = {
            "id": next_id,
            "申请编号": f"REQ-{next_id:04d}",
            "来源模块": source_module,
            "来源记录": source_record,
            "时段类型": kind,
            "原提交时间": submitted_at,
            "旧时段原文": legacy_text,
            "历史时区": _tz_label(start),
            "区间开始": _iso(start),
            "区间结束": _iso(end),
            "区间开始UTC": _iso_utc(start),
            "区间结束UTC": _iso_utc(end),
            "跨时区": (start.utcoffset() != end.utcoffset()),
            "片段粒度分钟": fragment_minutes,
            "片段总数": count,
            "时长小时": hours,
            "费用单价元每小时": RATE_PER_HOUR,
            "费用估算元": round(hours * RATE_PER_HOUR, 4),
            "掌管入口": entry,
            "progress_token": uuid.uuid4().hex,
            "状态": "进行中",
            "创建时间": _now(),
            "fragments": fragments,
        }
        rows.append(request)
        return request

    def open_request(
        self,
        start_text: str,
        end_text: str,
        source_module: str = "batch_export",
        fragment_minutes: int = 60,
        entry: str = ENTRY_INTERVAL,
    ) -> dict[str, Any]:
        """打开一笔新的区间申请（新入口）。"""
        if entry not in ENTRIES:
            return {"ok": False, "message": f"未知入口：{entry}"}
        if fragment_minutes <= 0:
            return {"ok": False, "message": "片段粒度必须为正整数分钟"}
        start = _parse_moment(start_text)
        end = _parse_moment(end_text)
        if start is None or end is None:
            return {"ok": False, "message": "开始/结束时刻必须带时区偏移，例如 2026-11-26T08:00:00+08:00"}
        if end <= start:
            return {"ok": False, "message": "结束时刻必须晚于开始时刻"}

        request = self._build_request(
            kind="interval",
            source_module=source_module,
            source_record="",
            start=start,
            end=end,
            fragment_minutes=fragment_minutes,
            entry=entry,
        )
        return {
            "ok": True,
            "message": f"区间申请已打开：{request['申请编号']}",
            "request": self._summary(request),
            "续领凭证": request["progress_token"],
        }

    # ---------- 旧记录核对与迁移 ----------

    def inspect_legacy(self, module: str, record_id: str) -> dict[str, Any]:
        """核对一条旧导出记录：能解释的给出真实区间，不能解释的保留原文和原因。"""
        if module not in LEGACY_MODULES:
            return {"ok": False, "message": f"模块 {module} 没有旧导出时段，支持：{'、'.join(LEGACY_MODULES)}"}
        record = self._find_legacy_record(module, record_id)
        if record is None:
            return {"ok": False, "message": f"{module} 中找不到记录 {record_id}"}

        code_field = "任务编号" if module == "batch_export" else "管道编号"
        resolution = resolve_legacy_period(record)
        base = {
            "ok": True,
            "module": module,
            "record_id": record.get("id"),
            "编号": record.get(code_field, ""),
            "原文本": resolution.get("原文本", ""),
            "原提交时间": record.get("提交时间", ""),
        }
        if not resolution["resolvable"]:
            return {**base, "可继续": False, "失败原因": resolution["失败原因"]}

        start, end = resolution["start"], resolution["end"]
        return {
            **base,
            "可继续": True,
            "时段类型": resolution["kind"],
            "历史时区": _tz_label(start),
            "实际区间": {
                "开始": _iso(start),
                "结束": _iso(end),
                "开始UTC": _iso_utc(start),
                "结束UTC": _iso_utc(end),
                "跨时区": start.utcoffset() != end.utcoffset(),
            },
        }

    def migrate_legacy(
        self,
        module: str,
        record_id: str,
        entry: str = ENTRY_INTERVAL,
        fragment_minutes: int = 180,
    ) -> dict[str, Any]:
        """把一条旧导出记录迁移成区间申请；同一记录重复迁移返回原申请。"""
        if entry not in ENTRIES:
            return {"ok": False, "message": f"未知入口：{entry}"}
        if module not in LEGACY_MODULES:
            return {"ok": False, "message": f"模块 {module} 没有旧导出时段，支持：{'、'.join(LEGACY_MODULES)}"}
        record = self._find_legacy_record(module, record_id)
        if record is None:
            return {"ok": False, "message": f"{module} 中找不到记录 {record_id}"}

        code_field = "任务编号" if module == "batch_export" else "管道编号"
        source_code = str(record.get(code_field, record_id))

        existing = next(
            (row for row in self._rows()
             if row.get("来源模块") == module and row.get("来源记录") == source_code),
            None,
        )
        if existing is not None:
            return {
                "ok": True,
                "already": True,
                "message": f"记录 {source_code} 已迁移为 {existing['申请编号']}，不重复建单",
                "request": self._summary(existing),
                "续领凭证": existing["progress_token"],
            }

        resolution = resolve_legacy_period(record)
        if not resolution["resolvable"]:
            return {
                "ok": False,
                "code": "UNRESOLVABLE_PERIOD",
                "message": f"旧记录 {source_code} 的时段无法解释，不允许继续",
                "原文本": resolution.get("原文本", ""),
                "失败原因": resolution["失败原因"],
            }

        request = self._build_request(
            kind=resolution["kind"],
            source_module=module,
            source_record=source_code,
            start=resolution["start"],
            end=resolution["end"],
            fragment_minutes=fragment_minutes,
            entry=entry,
            submitted_at=str(record.get("提交时间", "")),
            legacy_text=resolution.get("原文本", ""),
        )
        return {
            "ok": True,
            "already": False,
            "message": f"旧记录 {source_code} 已迁移为区间申请 {request['申请编号']}",
            "request": self._summary(request),
            "续领凭证": request["progress_token"],
        }

    # ---------- 领取进度 ----------

    def _summary(self, request: dict[str, Any]) -> dict[str, Any]:
        fragments = request["fragments"]
        return {
            "申请编号": request["申请编号"],
            "来源模块": request["来源模块"],
            "来源记录": request["来源记录"],
            "时段类型": request["时段类型"],
            "历史时区": request["历史时区"],
            "区间开始": request["区间开始"],
            "区间结束": request["区间结束"],
            "区间开始UTC": request["区间开始UTC"],
            "区间结束UTC": request["区间结束UTC"],
            "跨时区": request["跨时区"],
            "片段总数": request["片段总数"],
            "已签收数": sum(1 for f in fragments if f["state"] == STATE_SIGNED),
            "掌管入口": request["掌管入口"],
            "状态": request["状态"],
            "时长小时": request["时长小时"],
            "费用单价元每小时": request["费用单价元每小时"],
            "费用估算元": request["费用估算元"],
        }

    def list_requests(self) -> dict[str, Any]:
        return {
            "ok": True,
            "部署轮次": _DEPLOY_EPOCH,
            "items": [self._summary(row) for row in self._rows()],
        }

    def progress_detail(self, claim_id: str) -> dict[str, Any]:
        """领取进度详情：核对历史时区、实际区间、掌管入口，并发放续领凭证。"""
        request = self._find(claim_id)
        if request is None:
            return {"ok": False, "message": f"区间申请 {claim_id} 不存在"}
        if not request["progress_token"]:
            # 部署切换后凭证作废，从进度详情重新发放续领凭证
            request["progress_token"] = uuid.uuid4().hex

        fragments = request["fragments"]
        return {
            "ok": True,
            "申请编号": request["申请编号"],
            "来源模块": request["来源模块"],
            "来源记录": request["来源记录"],
            "时段类型": request["时段类型"],
            "旧时段原文": request["旧时段原文"],
            "原提交时间": request["原提交时间"],
            "历史时区": request["历史时区"],
            "实际区间": {
                "开始": request["区间开始"],
                "结束": request["区间结束"],
                "开始UTC": request["区间开始UTC"],
                "结束UTC": request["区间结束UTC"],
                "跨时区": request["跨时区"],
            },
            "费用": {
                "单价元每小时": request["费用单价元每小时"],
                "时长小时": request["时长小时"],
                "估算元": request["费用估算元"],
            },
            "掌管入口": request["掌管入口"],
            "续领凭证": request["progress_token"],
            "状态": request["状态"],
            "片段总数": request["片段总数"],
            "已签收数": sum(1 for f in fragments if f["state"] == STATE_SIGNED),
            "处理中数": sum(1 for f in fragments if f["state"] == STATE_CLAIMED),
            "待领取数": sum(1 for f in fragments if f["state"] == STATE_PENDING),
            "fragments": [dict(f) for f in fragments],
        }

    # ---------- 领取与签收 ----------

    def _check_progress_basis(
        self, request: dict[str, Any], entry: str
    ) -> dict[str, Any] | None:
        """新旧入口并行时，只有持有效进度依据的入口可以接续。"""
        owner = request["掌管入口"]
        if entry != owner:
            return {
                "ok": False,
                "code": "ENTRY_CONFLICT",
                "message": f"领取冲突：该申请由「{owner}」掌管，「{entry}」没有有效进度依据",
                "掌管入口": owner,
            }
        return None

    def _check_token(self, request: dict[str, Any], token: str) -> dict[str, Any] | None:
        if not token or token != request["progress_token"]:
            return {
                "ok": False,
                "code": "STALE_PROGRESS",
                "message": "进度依据已失效，请先从领取进度详情核对后再续领",
                "掌管入口": request["掌管入口"],
            }
        return None

    def claim_next(self, claim_id: str, entry: str, token: str) -> dict[str, Any]:
        """领取下一个待领取片段；处理中的片段对本入口重复交付，已签收的不交付。"""
        request = self._find(claim_id)
        if request is None:
            return {"ok": False, "message": f"区间申请 {claim_id} 不存在"}
        conflict = self._check_progress_basis(request, entry) or self._check_token(request, token)
        if conflict:
            return conflict

        fragments = request["fragments"]
        # 本入口处理中的片段（答复丢失后的重领）原样再交付，不算新片段
        in_flight = next(
            (f for f in fragments if f["state"] == STATE_CLAIMED and f["领取入口"] == entry),
            None,
        )
        if in_flight is not None:
            request["progress_token"] = uuid.uuid4().hex
            return {
                "ok": True,
                "redelivered": True,
                "message": f"片段 {in_flight['seq']} 仍在本入口处理中，重新交付",
                "fragment": dict(in_flight),
                "续领凭证": request["progress_token"],
                "剩余待领取": sum(1 for f in fragments if f["state"] == STATE_PENDING),
            }

        nxt = next((f for f in fragments if f["state"] == STATE_PENDING), None)
        if nxt is None:
            return {
                "ok": True,
                "done": True,
                "message": "没有待领取的片段",
                "已签收数": sum(1 for f in fragments if f["state"] == STATE_SIGNED),
                "续领凭证": request["progress_token"],
            }

        nxt["state"] = STATE_CLAIMED
        nxt["领取入口"] = entry
        nxt["领取时间"] = _now()
        request["progress_token"] = uuid.uuid4().hex
        return {
            "ok": True,
            "redelivered": False,
            "message": f"片段 {nxt['seq']} 已交付给「{entry}」",
            "fragment": dict(nxt),
            "续领凭证": request["progress_token"],
            "剩余待领取": sum(1 for f in fragments if f["state"] == STATE_PENDING),
        }

    def sign_fragment(self, claim_id: str, entry: str, token: str, seq: int) -> dict[str, Any]:
        """签收片段：已确认的片段不会再次交付，重复签收幂等返回。"""
        request = self._find(claim_id)
        if request is None:
            return {"ok": False, "message": f"区间申请 {claim_id} 不存在"}
        conflict = self._check_progress_basis(request, entry) or self._check_token(request, token)
        if conflict:
            return conflict

        fragment = next((f for f in request["fragments"] if f["seq"] == seq), None)
        if fragment is None:
            return {"ok": False, "message": f"片段 {seq} 不存在"}
        if fragment["state"] == STATE_SIGNED:
            return {
                "ok": True,
                "already_signed": True,
                "message": f"片段 {seq} 已签收，不重复交付",
                "fragment": dict(fragment),
                "续领凭证": request["progress_token"],
            }
        if fragment["state"] != STATE_CLAIMED or fragment["领取入口"] != entry:
            return {"ok": False, "message": f"片段 {seq} 未处于本入口处理中，不能签收"}

        fragment["state"] = STATE_SIGNED
        fragment["签收时间"] = _now()
        request["progress_token"] = uuid.uuid4().hex
        if all(f["state"] == STATE_SIGNED for f in request["fragments"]):
            request["状态"] = "已完成"
        return {
            "ok": True,
            "already_signed": False,
            "message": f"片段 {seq} 已签收",
            "fragment": dict(fragment),
            "续领凭证": request["progress_token"],
            "已签收数": sum(1 for f in request["fragments"] if f["state"] == STATE_SIGNED),
            "状态": request["状态"],
        }

    # ---------- 部署切换 ----------

    def deploy_switch(self) -> dict[str, Any]:
        """模拟部署切换：回收处理中片段、作废续领凭证，已签收进度保留。"""
        global _DEPLOY_EPOCH
        _DEPLOY_EPOCH += 1
        recycled = 0
        for request in self._rows():
            for fragment in request["fragments"]:
                if fragment["state"] == STATE_CLAIMED:
                    fragment["state"] = STATE_PENDING
                    fragment["领取入口"] = ""
                    fragment["领取时间"] = ""
                    recycled += 1
            request["progress_token"] = ""
        return {
            "ok": True,
            "部署轮次": _DEPLOY_EPOCH,
            "回收处理中片段": recycled,
            "message": "部署切换完成：处理中片段已回收，续领凭证已作废，已签收进度保留",
        }


interval_claim_service = IntervalClaimService()
