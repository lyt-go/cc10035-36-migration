# IoT设备数据接入与协议适配平台

面向IoT设备注册、多协议适配、消息路由与时序数据归集的设备数据接入平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 设备注册 | `device_registry` | 设备档案 | 设备编号、设备类型、协议类型 |
| 协议配置 | `protocol_cfg` | 协议配置 | 配置编号、协议名称、传输方式 |
| 报文解码 | `msg_decode` | 解码规则 | 规则编号、协议类型、报文标识 |
| 消息路由 | `msg_router` | 路由规则 | 规则编号、匹配Topic、目标Topic |
| 时序测点 | `ts_point` | 测点定义 | 测点编号、设备编号、测点名称 |
| 时序存储 | `ts_store` | 存储策略 | 策略编号、测点编号、存储引擎 |
| 降采样 | `downsample` | 降采样任务 | 任务编号、源测点、目标粒度 |
| 告警触发 | `alarm_trigger` | 告警规则 | 规则编号、关联测点、告警条件 |
| 固件升级 | `firmware_ota` | 升级任务 | 任务编号、目标设备、固件版本 |
| 网关管理 | `gateway_mgmt` | 网关节点 | 网关编号、网关地址、挂载设备数 |
| 设备影子 | `shadow_dev` | 影子记录 | 记录编号、设备编号、期望状态 |
| 数据断点 | `data_gap` | 断点记录 | 记录编号、设备编号、测点编号 |
| 批量导出 | `batch_export` | 导出任务 | 任务编号、设备范围、测点列表 |
| 规则引擎 | `rule_engine` | 联动规则 | 规则编号、触发条件、执行动作 |
| 边缘缓存 | `edge_cache` | 缓存配置 | 配置编号、网关编号、缓存大小 |
| 标签绑定 | `tag_binding` | 标签关系 | 关系编号、设备编号、标签键 |
| 数据流管道 | `data_stream` | 流管道 | 管道编号、输入源、处理算子链 |
| 聚合分发 | `aggregate_sink` | 分发任务 | 任务编号、数据窗口、聚合函数 |

## 区间申请（旧导出时段迁移）

数据流管道和批量导出的两套旧导出时段（「过去一天」、带偏移的明确时刻）可迁移为区间申请：

- 「过去一天」锚定原提交时间，截止时刻固定；带偏移的明确时刻保留实际区间；
  无法解释的旧记录展示原文本和失败原因，不允许继续。
- 领取进度详情展示历史时区、实际区间和掌管入口；新旧入口并行时，
  一笔申请只由持有效进度依据（掌管入口 + 续领凭证）的入口接续，已签收片段不会再次交付。
- 费用按同次申请的真实区间计（0.05 元/小时），不因隔天操作重新按当前时间取数。

接口在 `backend/app/routers/interval_claim.py`（`/api/interval-claims`），
领域逻辑在 `backend/app/services/interval_claim.py`，前端页面 `frontend/src/views/IntervalClaimsView.vue`
（路由 `/interval-claims`）。场景测试见 `backend/tests/test_interval_claim.py`。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
