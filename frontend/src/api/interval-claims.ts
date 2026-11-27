/** 区间申请接口封装：旧导出时段迁移、领取进度、片段领取与签收。 */
import { request } from './client'

export type Fragment = {
  seq: number
  开始: string
  结束: string
  开始UTC: string
  结束UTC: string
  state: string
  领取入口: string
  领取时间: string
  签收时间: string
}

export type ClaimSummary = {
  申请编号: string
  来源模块: string
  来源记录: string
  时段类型: string
  历史时区: string
  区间开始: string
  区间结束: string
  区间开始UTC: string
  区间结束UTC: string
  跨时区: boolean
  片段总数: number
  已签收数: number
  掌管入口: string
  状态: string
  时长小时: number
  费用单价元每小时: number
  费用估算元: number
}

export type ClaimDetail = {
  ok: boolean
  message?: string
  申请编号: string
  来源模块: string
  来源记录: string
  时段类型: string
  旧时段原文: string
  原提交时间: string
  历史时区: string
  实际区间: { 开始: string; 结束: string; 开始UTC: string; 结束UTC: string; 跨时区: boolean }
  费用: { 单价元每小时: number; 时长小时: number; 估算元: number }
  掌管入口: string
  续领凭证: string
  状态: string
  片段总数: number
  已签收数: number
  处理中数: number
  待领取数: number
  fragments: Fragment[]
}

export type InspectResult = {
  ok: boolean
  message?: string
  编号?: string
  原文本?: string
  原提交时间?: string
  可继续?: boolean
  失败原因?: string
  时段类型?: string
  历史时区?: string
  实际区间?: { 开始: string; 结束: string; 开始UTC: string; 结束UTC: string; 跨时区: boolean }
}

export type ClaimResult = {
  ok: boolean
  code?: string
  message: string
  掌管入口?: string
  fragment?: Fragment
  续领凭证?: string
  done?: boolean
  redelivered?: boolean
  already_signed?: boolean
  剩余待领取?: number
  已签收数?: number
  状态?: string
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return (await response.json()) as T
}

export async function listClaims(): Promise<{ ok: boolean; 部署轮次: number; items: ClaimSummary[] }> {
  const response = await request('/api/interval-claims')
  return await response.json()
}

export async function openClaim(payload: {
  start: string
  end: string
  source_module: string
  fragment_minutes: number
}): Promise<{ ok: boolean; message: string; request?: ClaimSummary; 续领凭证?: string }> {
  return await post('/api/interval-claims', payload)
}

export async function inspectLegacy(module: string, recordId: string): Promise<InspectResult> {
  const response = await request(`/api/interval-claims/legacy/${module}/${recordId}`)
  return await response.json()
}

export async function migrateLegacy(payload: {
  module: string
  record_id: string
  fragment_minutes: number
}): Promise<{ ok: boolean; message: string; 原文本?: string; 失败原因?: string; request?: ClaimSummary }> {
  return await post('/api/interval-claims/migrate', payload)
}

export async function claimDetail(claimId: string): Promise<ClaimDetail> {
  const response = await request(`/api/interval-claims/${claimId}`)
  return await response.json()
}

export async function claimNext(claimId: string, entry: string, token: string): Promise<ClaimResult> {
  return await post(`/api/interval-claims/${claimId}/claim-next`, { entry, token })
}

export async function signFragment(
  claimId: string,
  entry: string,
  token: string,
  seq: number,
): Promise<ClaimResult> {
  return await post(`/api/interval-claims/${claimId}/sign`, { entry, token, seq })
}

export async function deploySwitch(): Promise<{ ok: boolean; message: string; 部署轮次: number }> {
  return await post('/api/interval-claims/deploy-switch', {})
}
