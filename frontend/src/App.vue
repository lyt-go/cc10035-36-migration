<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">IoT设备数据接入与协议适配平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向IoT设备注册、多协议适配、消息路由与时序数据归集的设备数据接入平台。</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "设备注册", path: "/device_registry" }, { label: "协议配置", path: "/protocol_cfg" }, { label: "报文解码", path: "/msg_decode" }, { label: "消息路由", path: "/msg_router" }, { label: "时序测点", path: "/ts_point" }, { label: "时序存储", path: "/ts_store" }, { label: "降采样", path: "/downsample" }, { label: "告警触发", path: "/alarm_trigger" }, { label: "固件升级", path: "/firmware_ota" }, { label: "网关管理", path: "/gateway_mgmt" }, { label: "设备影子", path: "/shadow_dev" }, { label: "数据断点", path: "/data_gap" }, { label: "批量导出", path: "/batch_export" }, { label: "区间申请", path: "/interval-claims" }, { label: "规则引擎", path: "/rule_engine" }, { label: "边缘缓存", path: "/edge_cache" }, { label: "标签绑定", path: "/tag_binding" }, { label: "数据流管道", path: "/data_stream" }, { label: "聚合分发", path: "/aggregate_sink" }]
</script>
