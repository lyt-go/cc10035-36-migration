<template>
  <section class="page" data-module="interval-claims">
    <header class="page-head">
      <div>
        <h2>区间申请</h2>
        <p class="page-desc">
          数据流管道和批量导出的旧导出时段迁移为区间申请：先核对历史时区和实际区间，再继续没拿到的片段。
          费用按同次申请的真实区间计，每小时 0.05 元。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh-list" type="button" @click="reload">刷新列表</button>
        <button class="btn ghost" data-testid="deploy-switch" type="button" @click="onDeploySwitch">
          模拟部署切换
        </button>
      </div>
    </header>

    <!-- 打开新区间申请 -->
    <form class="analysis-form" data-testid="open-form" @submit.prevent="submitOpen">
      <label>
        <span>开始时刻（带偏移）</span>
        <input v-model="openForm.start" data-testid="open-start" placeholder="2026-11-26T08:00:00+08:00" />
      </label>
      <label>
        <span>结束时刻（带偏移）</span>
        <input v-model="openForm.end" data-testid="open-end" placeholder="2026-11-26T02:00:00+00:00" />
      </label>
      <label>
        <span>来源模块</span>
        <select v-model="openForm.source_module" data-testid="open-module">
          <option value="batch_export">批量导出</option>
          <option value="data_stream">数据流管道</option>
        </select>
      </label>
      <label>
        <span>片段粒度（分钟）</span>
        <input v-model.number="openForm.fragment_minutes" data-testid="open-granularity" type="number" min="1" />
      </label>
      <button class="btn primary" data-testid="open-submit" type="submit">打开区间申请</button>
    </form>

    <!-- 旧记录核对与迁移 -->
    <form class="analysis-form" data-testid="migrate-form" @submit.prevent="submitMigrate">
      <label>
        <span>旧记录模块</span>
        <select v-model="migrateForm.module" data-testid="migrate-module">
          <option value="data_stream">数据流管道</option>
          <option value="batch_export">批量导出</option>
        </select>
      </label>
      <label>
        <span>记录编号</span>
        <input v-model="migrateForm.record_id" data-testid="migrate-record" placeholder="DATA-0004 / BATC-0005" />
      </label>
      <label>
        <span>片段粒度（分钟）</span>
        <input v-model.number="migrateForm.fragment_minutes" data-testid="migrate-granularity" type="number" min="1" />
      </label>
      <button class="btn" data-testid="inspect-submit" type="button" @click="submitInspect">核对旧记录</button>
      <button class="btn primary" data-testid="migrate-submit" type="submit">迁移为区间申请</button>
    </form>

    <div v-if="inspectResult" class="inspect-box" data-testid="inspect-result">
      <template v-if="inspectResult.可继续">
        <p>
          记录 {{ inspectResult.编号 }} 可继续：时段类型 {{ inspectResult.时段类型 }}，历史时区
          {{ inspectResult.历史时区 }}，实际区间 {{ inspectResult.实际区间?.开始 }} ~
          {{ inspectResult.实际区间?.结束 }}
          <span v-if="inspectResult.实际区间?.跨时区">（跨时区）</span>
        </p>
      </template>
      <template v-else>
        <p class="error-text">
          记录 {{ inspectResult.编号 }} 不可继续。原文本：「{{ inspectResult.原文本 }}」；原因：{{
            inspectResult.失败原因
          }}
        </p>
      </template>
    </div>

    <!-- 申请列表 -->
    <table class="data-table">
      <thead>
        <tr>
          <th>申请编号</th>
          <th>来源</th>
          <th>时段类型</th>
          <th>实际区间</th>
          <th>签收进度</th>
          <th>掌管入口</th>
          <th>费用估算</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in claims" :key="item.申请编号" :data-testid="`claim-${item.申请编号}`">
          <td>{{ item.申请编号 }}</td>
          <td>{{ item.来源模块 }}<template v-if="item.来源记录"> / {{ item.来源记录 }}</template></td>
          <td>{{ item.时段类型 }}</td>
          <td>{{ item.区间开始 }} ~ {{ item.区间结束 }}<span v-if="item.跨时区">（跨时区）</span></td>
          <td>{{ item.已签收数 }}/{{ item.片段总数 }}</td>
          <td>{{ item.掌管入口 }}</td>
          <td>{{ item.费用估算元 }} 元</td>
          <td>{{ item.状态 }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`detail-${item.申请编号}`" @click="openDetail(item.申请编号)">
              领取进度
            </button>
          </td>
        </tr>
        <tr v-if="!claims.length">
          <td colspan="9" class="empty-state">暂无区间申请，可打开新申请或迁移旧记录</td>
        </tr>
      </tbody>
    </table>

    <!-- 领取进度详情 -->
    <div v-if="detail" class="detail-panel" data-testid="progress-detail">
      <h3>领取进度详情：{{ detail.申请编号 }}</h3>
      <dl class="dag-detail">
        <dt>历史时区</dt>
        <dd data-testid="detail-tz">{{ detail.历史时区 }}</dd>
        <dt>实际区间</dt>
        <dd data-testid="detail-range">
          {{ detail.实际区间.开始 }} ~ {{ detail.实际区间.结束 }}
          <span v-if="detail.实际区间.跨时区">（跨时区）</span>
        </dd>
        <dt v-if="detail.原提交时间">原提交时间</dt>
        <dd v-if="detail.原提交时间">{{ detail.原提交时间 }}</dd>
        <dt>费用</dt>
        <dd data-testid="detail-billing">
          {{ detail.费用.时长小时 }} 小时 × {{ detail.费用.单价元每小时 }} 元/小时 =
          {{ detail.费用.估算元 }} 元
        </dd>
        <dt>掌管入口</dt>
        <dd data-testid="detail-owner">{{ detail.掌管入口 }}</dd>
        <dt>签收进度</dt>
        <dd data-testid="detail-progress">
          已签收 {{ detail.已签收数 }} / {{ detail.片段总数 }}（处理中 {{ detail.处理中数 }}，待领取
          {{ detail.待领取数 }}）
        </dd>
      </dl>

      <div class="page-actions">
        <button class="btn primary" data-testid="claim-next" type="button" @click="onClaimNext(ENTRY_INTERVAL)">
          领取下一片段（区间申请入口）
        </button>
        <button
          class="btn"
          data-testid="sign-current"
          type="button"
          :disabled="!inFlight"
          @click="onSign"
        >
          签收当前片段<template v-if="inFlight">（第 {{ inFlight.seq }} 片）</template>
        </button>
        <button class="btn ghost" data-testid="claim-legacy" type="button" @click="onClaimNext(ENTRY_LEGACY)">
          旧导出入口续领
        </button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>片段</th>
            <th>区间开始</th>
            <th>区间结束</th>
            <th>状态</th>
            <th>领取入口</th>
            <th>签收时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="frag in detail.fragments"
            :key="frag.seq"
            :data-testid="`fragment-${frag.seq}`"
            :data-state="frag.state"
          >
            <td>第 {{ frag.seq }} 片</td>
            <td>{{ frag.开始 }}</td>
            <td>{{ frag.结束 }}</td>
            <td>{{ frag.state }}</td>
            <td>{{ frag.领取入口 || '—' }}</td>
            <td>{{ frag.签收时间 || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>共 {{ claims.length }} 笔区间申请</span>
      <span v-if="notice" class="notice-text" data-testid="notice">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text" data-testid="error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  claimDetail,
  claimNext,
  deploySwitch,
  inspectLegacy,
  listClaims,
  migrateLegacy,
  openClaim,
  signFragment,
  type ClaimDetail,
  type ClaimSummary,
  type InspectResult,
} from '@/api/interval-claims'

const ENTRY_INTERVAL = '区间申请入口'
const ENTRY_LEGACY = '旧导出入口'

const claims = ref<ClaimSummary[]>([])
const detail = ref<ClaimDetail | null>(null)
const token = ref('')
const errorMessage = ref('')
const notice = ref('')
const inspectResult = ref<InspectResult | null>(null)

const openForm = ref({ start: '', end: '', source_module: 'batch_export', fragment_minutes: 60 })
const migrateForm = ref({ module: 'data_stream', record_id: '', fragment_minutes: 180 })

const inFlight = computed(
  () =>
    detail.value?.fragments.find(
      (frag) => frag.state === '处理中' && frag.领取入口 === detail.value?.掌管入口,
    ) ?? null,
)

function showError(error: unknown, fallback: string) {
  errorMessage.value = error instanceof Error ? error.message : fallback
  notice.value = ''
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listClaims()
    claims.value = payload.items
  } catch (error) {
    showError(error, '区间申请列表读取失败')
  }
}

async function submitOpen() {
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await openClaim(openForm.value)
    if (!result.ok) throw new Error(result.message)
    notice.value = result.message
    await reload()
  } catch (error) {
    showError(error, '打开区间申请失败')
  }
}

async function submitInspect() {
  errorMessage.value = ''
  notice.value = ''
  inspectResult.value = null
  try {
    const result = await inspectLegacy(migrateForm.value.module, migrateForm.value.record_id)
    if (!result.ok) throw new Error(result.message ?? '核对失败')
    inspectResult.value = result
  } catch (error) {
    showError(error, '旧记录核对失败')
  }
}

async function submitMigrate() {
  errorMessage.value = ''
  notice.value = ''
  inspectResult.value = null
  try {
    const result = await migrateLegacy(migrateForm.value)
    if (!result.ok) {
      inspectResult.value = {
        ok: false,
        可继续: false,
        编号: migrateForm.value.record_id,
        原文本: result.原文本,
        失败原因: result.失败原因 ?? result.message,
      }
      return
    }
    notice.value = result.message
    await reload()
  } catch (error) {
    showError(error, '迁移失败')
  }
}

async function openDetail(claimId: string) {
  errorMessage.value = ''
  try {
    const payload = await claimDetail(claimId)
    if (!payload.ok) throw new Error(payload.message ?? '进度读取失败')
    detail.value = payload
    token.value = payload.续领凭证
  } catch (error) {
    showError(error, '领取进度读取失败')
  }
}

async function refreshDetail() {
  if (detail.value) await openDetail(detail.value.申请编号)
}

async function onClaimNext(entry: string) {
  if (!detail.value) return
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await claimNext(detail.value.申请编号, entry, token.value)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    if (result.续领凭证) token.value = result.续领凭证
    notice.value = result.message
    await refreshDetail()
  } catch (error) {
    showError(error, '领取失败')
  }
}

async function onSign() {
  if (!detail.value || !inFlight.value) return
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await signFragment(detail.value.申请编号, ENTRY_INTERVAL, token.value, inFlight.value.seq)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    if (result.续领凭证) token.value = result.续领凭证
    notice.value = result.message
    await refreshDetail()
    await reload()
  } catch (error) {
    showError(error, '签收失败')
  }
}

async function onDeploySwitch() {
  errorMessage.value = ''
  try {
    const result = await deploySwitch()
    notice.value = result.message
    await refreshDetail()
    await reload()
  } catch (error) {
    showError(error, '部署切换模拟失败')
  }
}

onMounted(reload)
</script>

<style scoped>
.inspect-box {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 13px;
}
.detail-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  margin-top: 14px;
}
.detail-panel h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.detail-panel .page-actions {
  display: flex;
  gap: 8px;
  margin: 10px 0;
}
.notice-text {
  color: #15803d;
}
.analysis-form label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}
</style>
