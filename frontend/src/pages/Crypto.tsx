import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchAPI } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useToast } from '@panwatch/base-ui/components/ui/toast'

type Position = { symbol: string; quantity: string }
type Rule = { symbol: string; op: '>=' | '<='; price: string; cooldown_minutes: number; notify: boolean }
type Config = { exchange: string; interval_seconds: number; positions: Position[]; alerts: Rule[] }
type Report = { id: string; at: string; status: string; markdown?: string; error_type?: string; delivery: { status: string } }
type View = {
  config: Config
  snapshot: { status: string; observed_at?: string; error_type?: string; positions?: (Position & { price: string; value: string; quote_currency: string; source_time: string })[]; totals_by_quote_currency?: Record<string, string> }
  reports: Report[]
  events: { at: string; type: string; symbol: string; price: string; delivery: { status: string } }[]
}

const blank: Config = { exchange: 'okx', interval_seconds: 60, positions: [], alerts: [] }

export default function Crypto() {
  const { t } = useTranslation('crypto')
  const { toast } = useToast()
  const [view, setView] = useState<View>()
  const [config, setConfig] = useState<Config>(blank)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notify, setNotify] = useState(false)
  const [error, setError] = useState('')
  const mounted = useRef(true)
  const time = (value: string) => new Date(value).toLocaleString()
  const status = (value: string) => t(`statuses.${value}`, { defaultValue: value })
  useEffect(() => {
    mounted.current = true
    const load = async (initial = false) => {
      try {
        const next = await fetchAPI<View>('/crypto')
        if (!mounted.current) return
        setView(next)
        if (initial) setConfig(next.config)
        setError('')
      } catch (e) {
        if (mounted.current) setError(e instanceof Error ? e.message : t('loadFailed'))
      }
    }
    void load(true)
    const timer = window.setInterval(() => { void load() }, 5000)
    return () => { mounted.current = false; window.clearInterval(timer) }
  }, [t])
  const change = (next: Config) => { setConfig(next); setDirty(true) }
  const action = async (kind: 'save' | 'refresh' | 'report') => {
    setBusy(true)
    try {
      if (kind === 'report') {
        await fetchAPI('/crypto/reports', { method: 'POST', body: JSON.stringify({ notify }) })
        toast(t('queued'), 'success')
        setView(await fetchAPI<View>('/crypto'))
      } else {
        const next = await fetchAPI<View>(kind === 'save' ? '/crypto/config' : '/crypto/refresh', {
          method: kind === 'save' ? 'PUT' : 'POST', timeoutMs: 180000,
          ...(kind === 'save' ? { body: JSON.stringify(config) } : {}),
        })
        setView(next)
        if (kind === 'save') { setConfig(next.config); setDirty(false) }
        toast(t(kind === 'save' ? 'saved' : 'refreshed'), 'success')
      }
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : t('loadFailed'))
    } finally { setBusy(false) }
  }
  const running = view?.reports.some(report => report.status === 'running')
  const disabled = busy || !view
  return <div className="space-y-6 p-4 sm:p-6 max-w-6xl mx-auto">
    <header className="space-y-2">
      <h1 className="text-2xl font-semibold">{t('title')}</h1>
      <p className="text-sm text-muted-foreground">{t('intro')}</p>
      <Link className="text-primary underline text-sm" to="/settings">{t('settings')}</Link>
      {busy && <p role="status" className="text-sm text-muted-foreground">{t('working')}</p>}
    </header>
    {error && <p role="alert" className="rounded-xl border border-destructive p-3 text-sm break-words">{error}</p>}
    <section className="rounded-2xl border border-border bg-card p-4 space-y-4">
      <h2 className="font-semibold">{t('holdings')}</h2>
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="space-y-2 text-sm">{t('exchange')}
          <Select value={config.exchange} onValueChange={exchange => change({ ...config, exchange })} disabled={disabled}>
            <SelectTrigger aria-label={t('exchange')}><SelectValue /></SelectTrigger>
            <SelectContent>{['okx', 'binance', 'kraken'].map(exchange => <SelectItem key={exchange} value={exchange}>{exchange}</SelectItem>)}</SelectContent>
          </Select>
        </label>
        <label className="space-y-2 text-sm">{t('interval')}
          <Input type="number" min={60} max={3600} value={config.interval_seconds} disabled={disabled}
            onChange={event => change({ ...config, interval_seconds: Number(event.target.value) })} />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{t('decimalHint')}</p>
      {config.positions.map((position, index) => <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2" key={index}>
        <Input aria-label={t('symbol', { n: index + 1 })} value={position.symbol} placeholder="BTC/USDT" disabled={disabled}
          onChange={event => change({ ...config, positions: config.positions.map((p, i) => i === index ? { ...p, symbol: event.target.value.toUpperCase() } : p) })} />
        <Input aria-label={t('quantity', { n: index + 1 })} value={position.quantity} inputMode="decimal" disabled={disabled}
          onChange={event => change({ ...config, positions: config.positions.map((p, i) => i === index ? { ...p, quantity: event.target.value } : p) })} />
        <Button variant="outline" disabled={disabled} onClick={() => change({ ...config, positions: config.positions.filter((_, i) => i !== index), alerts: config.alerts.filter(rule => rule.symbol !== position.symbol) })}>{t('remove')}</Button>
      </div>)}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={disabled || config.positions.length >= 8} onClick={() => change({ ...config, positions: [...config.positions, { symbol: '', quantity: '' }] })}>{t('addHolding')}</Button>
        <Button disabled={disabled || !dirty} onClick={() => { void action('save') }}>{t('save')}</Button>
        <Button variant="outline" disabled={disabled || !dirty} onClick={() => { if (view) setConfig(view.config); setDirty(false) }}>{t('cancel')}</Button>
      </div>
      {dirty && <p role="status" className="text-sm text-muted-foreground">{t('unsaved')}</p>}
      <h3 className="font-medium">{t('thresholds')}</h3>
      <p className="text-xs text-muted-foreground">{t('thresholdHint')}</p>
      {config.alerts.map((rule, index) => <div key={index} className="grid sm:grid-cols-2 gap-2 border border-border rounded-xl p-3">
        <label className="text-sm">{t('pair')}
          <Select value={rule.symbol} onValueChange={symbol => change({ ...config, alerts: config.alerts.map((r, i) => i === index ? { ...r, symbol } : r) })} disabled={disabled}>
            <SelectTrigger aria-label={t('pair')}><SelectValue /></SelectTrigger><SelectContent>{config.positions.filter(p => p.symbol).map(p => <SelectItem key={p.symbol} value={p.symbol}>{p.symbol}</SelectItem>)}</SelectContent>
          </Select>
        </label>
        <label className="text-sm">{t('condition')}
          <Select value={rule.op} onValueChange={op => change({ ...config, alerts: config.alerts.map((r, i) => i === index ? { ...r, op: op as Rule['op'] } : r) })} disabled={disabled}>
            <SelectTrigger aria-label={t('condition')}><SelectValue /></SelectTrigger><SelectContent><SelectItem value=">=">{t('above')}</SelectItem><SelectItem value="<=">{t('below')}</SelectItem></SelectContent>
          </Select>
        </label>
        <label className="text-sm">{t('price')}<Input value={rule.price} inputMode="decimal" disabled={disabled}
          onChange={event => change({ ...config, alerts: config.alerts.map((r, i) => i === index ? { ...r, price: event.target.value } : r) })} /></label>
        <label className="text-sm">{t('cooldown')}<Input type="number" min={1} max={10080} value={rule.cooldown_minutes} disabled={disabled}
          onChange={event => change({ ...config, alerts: config.alerts.map((r, i) => i === index ? { ...r, cooldown_minutes: Number(event.target.value) } : r) })} /></label>
        <label className="flex gap-2 items-center text-sm"><input type="checkbox" checked={rule.notify} disabled={disabled}
          onChange={event => change({ ...config, alerts: config.alerts.map((r, i) => i === index ? { ...r, notify: event.target.checked } : r) })} />{t('sendThreshold')}</label>
        <Button variant="outline" disabled={disabled} onClick={() => change({ ...config, alerts: config.alerts.filter((_, i) => i !== index) })}>{t('remove')}</Button>
      </div>)}
      <Button variant="outline" disabled={disabled || !config.positions[0]?.symbol || config.alerts.length >= 16}
        onClick={() => change({ ...config, alerts: [...config.alerts, { symbol: config.positions[0].symbol, op: '>=', price: '', cooldown_minutes: 60, notify: false }] })}>{t('addThreshold')}</Button>
    </section>
    <section className="rounded-2xl border border-border bg-card p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">{t('valuation')}</h2>
        <span role="status" className="text-sm text-muted-foreground">{status(view?.snapshot.status || 'loading')}</span>
        <Button variant="outline" disabled={disabled || dirty || !config.positions.length} onClick={() => { void action('refresh') }}>{t('refresh')}</Button>
      </div>
      {view?.snapshot.status !== 'ok' && <p className="text-sm text-muted-foreground">{t('notCurrent')}</p>}
      {view?.snapshot.error_type && <p className="text-sm">{view.snapshot.error_type}</p>}
      {view?.snapshot.positions?.map(position => <div className="rounded-xl border border-border p-3 text-sm space-y-1 break-words" key={position.symbol}>
        <p className="font-medium">{position.symbol} · {position.quantity}</p>
        <p>{t('price')}: {position.price} {position.quote_currency}</p>
        <p>{t('value')}: {position.value} {position.quote_currency}</p>
        <p className="text-xs text-muted-foreground">{t('source')}: {time(position.source_time)}</p>
      </div>)}
      {Object.entries(view?.snapshot.totals_by_quote_currency || {}).map(([currency, total]) => <p className="font-medium break-words" key={currency}>{t('total')}: {total} {currency}</p>)}
      <p className="text-xs text-muted-foreground">{t('valuationHint')}</p>
    </section>
    <section className="rounded-2xl border border-border bg-card p-4 space-y-4">
      <h2 className="font-semibold">{t('reports')}</h2>
      <p className="text-sm text-muted-foreground">{t('researchHint')}</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={notify} onChange={event => setNotify(event.target.checked)} />{t('sendReport')}</label>
      <Button disabled={disabled || dirty || running || !config.positions.length} onClick={() => { void action('report') }}>{running ? t('running') : t('createReport')}</Button>
      {view?.reports.map(report => <details key={report.id} className="border border-border rounded-xl p-3">
        <summary className="cursor-pointer text-sm break-words">{time(report.at)} · {status(report.status)} · {t('delivery')}: {status(report.delivery.status)}</summary>
        {report.error_type && <p role="status" className="text-sm mt-2">{report.error_type}</p>}
        <div className="prose dark:prose-invert prose-sm max-w-none break-words overflow-x-auto scrollbar mt-3"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: () => null }}>{report.markdown || ''}</ReactMarkdown></div>
      </details>)}
    </section>
    <section className="rounded-2xl border border-border bg-card p-4 space-y-3">
      <h2 className="font-semibold">{t('events')}</h2>
      {!view?.events.length && <p className="text-sm text-muted-foreground">{t('noEvents')}</p>}
      {view?.events.map((event, index) => <p key={index} className="text-sm break-words">{time(event.at)} · {event.symbol} · {event.price} · {status(event.delivery.status)}</p>)}
    </section>
  </div>
}
