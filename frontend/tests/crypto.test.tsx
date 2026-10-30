import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fetchAPI } from '@panwatch/api'
import { ToastProvider } from '@panwatch/base-ui/components/ui/toast'
import Crypto from '@/pages/Crypto'
import i18n from '@/i18n'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn() }))
const config = { exchange: 'okx', interval_seconds: 60, positions: [{ symbol: 'BTC/USDT', quantity: '0.1234567890123456789' }], alerts: [] }
const state = { config, snapshot: { status: 'stale', positions: [{ ...config.positions[0], price: '100', value: '12.34567890123456789', quote_currency: 'USDT', source_time: '2026-10-30T12:00:00Z' }] }, reports: [], events: [] }
beforeEach(async () => {
  vi.resetAllMocks()
  await i18n.loadNamespaces('crypto')
  vi.mocked(fetchAPI).mockResolvedValue(state)
})
afterEach(cleanup)
function open() { render(<MemoryRouter><ToastProvider><Crypto /></ToastProvider></MemoryRouter>) }

it('preserves exact decimal edits, blocks analysis of drafts, and discards without writing', async () => {
  const user = userEvent.setup()
  open()
  const quantity = await screen.findByRole('textbox', { name: '数量 1' })
  await waitFor(() => expect((quantity as HTMLInputElement).value).toBe(config.positions[0].quantity))
  await user.clear(quantity)
  await user.type(quantity, '0.000000000000000001')
  expect((screen.getByRole('button', { name: '生成 Crypto 报告' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '撤销草稿' }))
  expect((quantity as HTMLInputElement).value).toBe(config.positions[0].quantity)
  expect(vi.mocked(fetchAPI).mock.calls.every(([, options]) => !options?.method)).toBe(true)
})

it('writes decimal strings and keeps notification opt-in off', async () => {
  const user = userEvent.setup()
  open()
  const quantity = await screen.findByRole('textbox', { name: '数量 1' })
  await waitFor(() => expect((quantity as HTMLInputElement).value).toBe(config.positions[0].quantity))
  await user.clear(quantity)
  await user.type(quantity, '0.000000000000000001')
  await user.click(screen.getByRole('button', { name: '保存全部配置' }))
  const saved = vi.mocked(fetchAPI).mock.calls.find(([path]) => path === '/crypto/config')
  expect(JSON.parse(saved?.[1]?.body as string).positions[0].quantity).toBe('0.000000000000000001')
  expect((screen.getByRole('checkbox', { name: /本次完成后发送/ }) as HTMLInputElement).checked).toBe(false)
})

it('labels stale values and shows a failed mutation without claiming success', async () => {
  const user = userEvent.setup()
  open()
  await screen.findByText('行情已过期')
  expect(screen.getByText(/旧快照若仍可见/)).toBeTruthy()
  vi.mocked(fetchAPI).mockRejectedValueOnce(new Error('Controlled quote failure'))
  await user.click(screen.getByRole('button', { name: '立即刷新' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Controlled quote failure')
})
