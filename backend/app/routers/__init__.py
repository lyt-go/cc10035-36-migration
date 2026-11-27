"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import cross_module, interval_claim, resource

ROUTERS = [cross_module, interval_claim, resource]
