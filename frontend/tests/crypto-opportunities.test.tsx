import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fetchAPI } from '@panwatch/api'
import { ToastProvider } from '@panwatch/base-ui/components/ui/toast'
import CryptoOpportunities from '@/pages/CryptoOpportunities'
import i18n from '@/i18n'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn() }))
const settings = { exchange: 'okx', quote_currency: 'USDT', limit: 10, min_quote_volume: '10000000', max_spread_pct: '0.3', reviewed_plain_assets: ['BTC', 'ETH'], deadline_seconds: 180 }
const state = { settings, job: {}, captured_count: 1, current_count: 0, coverage: { selected_count: 2, market_eligible_count: 2 }, exclusions: { book_time_missing: 1 }, items: [{ instrument_key: 'CRYPTO:okx:BTC/USDT', exchange: 'okx', symbol: 'BTC/USDT', held: false, fresh: false, period: { technical_score: 91, state: 'matched', strategy_tags: ['trend_follow'], strategy_labels: ['均线多头'], source_close_ms: 1793404800000, snapshot_id: 'test-captured-input', profile_version: 'test-profile', rules_version: 'test-rules' }, snapshot: { indicators: { ma20: 0.00000001, rsi6: 50, macd_hist: 0.01, atr: 0.000001 } } }] }
beforeEach(async () => { vi.resetAllMocks(); await i18n.changeLanguage('zh-CN'); await i18n.loadNamespaces('crypto'); vi.mocked(fetchAPI).mockResolvedValue(state) })
afterEach(cleanup)
function open() { render(<MemoryRouter><ToastProvider><CryptoOpportunities /></ToastProvider></MemoryRouter>) }

it('shows historical evidence and exclusion reasons without claiming calibrated risk', async () => {
  const user = userEvent.setup(); open()
  await screen.findByText('BTC/USDT · okx')
  expect(screen.getByText(/规则匹配.*历史快照/)).toBeTruthy()
  await user.click(screen.getByText('查看证据'))
  expect(await screen.findByText(/test-captured-input/)).toBeTruthy()
  await user.click(screen.getByText('数据覆盖与排除原因'))
  expect(screen.getByText(/盘口源时间缺失/)).toBeTruthy()
})

it('rejects invalid settings before writing and keeps a draft across filter loads', async () => {
  const user = userEvent.setup(); open()
  const limit = await screen.findByRole('spinbutton', { name: '最多分析数量（1–10）' })
  await user.clear(limit); await user.type(limit, '11')
  await user.click(screen.getByRole('button', { name: '保存并扫描' }))
  expect(await screen.findByText('数量须为1–10的整数。')).toBeTruthy()
  expect(vi.mocked(fetchAPI).mock.calls.every(([, options]) => !options?.method)).toBe(true)
  await user.click(screen.getByRole('combobox', { name: '分析周期' })); await user.click(screen.getByRole('option', { name: '1小时线' }))
  await waitFor(() => expect(vi.mocked(fetchAPI).mock.calls.some(([path]) => path.includes('timeframe=1h'))).toBe(true))
  expect((limit as HTMLInputElement).value).toBe('11')
})

it('starts explicit bounded work and allows cancelling without notification controls', async () => {
  const user = userEvent.setup(); open(); await screen.findByText('BTC/USDT · okx')
  vi.mocked(fetchAPI).mockImplementation(async (path) => path.endsWith('/scans') ? { status: 'running' } : { ...state, job: { status: 'running' } } as never)
  await user.click(screen.getByRole('button', { name: '保存并扫描' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '保存并扫描' }) as HTMLButtonElement).disabled).toBe(true))
  const call = vi.mocked(fetchAPI).mock.calls.find(([path]) => path.endsWith('/scans'))
  expect(JSON.parse(call?.[1]?.body as string)).toEqual(settings)
  await user.click(screen.getByRole('button', { name: '取消扫描' }))
  expect(vi.mocked(fetchAPI).mock.calls.some(([path]) => path.endsWith('/cancel'))).toBe(true)
  expect(screen.queryByRole('checkbox')).toBeNull()
})
