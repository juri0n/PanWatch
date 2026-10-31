import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { validCryptoDecimal } from '@/lib/crypto-form'

type Settings = { exchange: string; quote_currency: string; limit: number; min_quote_volume: string; max_spread_pct: string; reviewed_plain_assets: string[]; deadline_seconds: number }
type Period = { technical_score: number; state: string; strategy_tags: string[]; strategy_labels: string[]; snapshot_id: string; source_close_ms: number; change_window: string; rules_version: string; profile_version: string }
type View = { settings: Settings; job: { status?: string }; asof_ms?: number; coverage: Record<string, number>; captured_count: number; current_count: number; scan_config?: Settings; exclusions?: Record<string, number>; probe_status?: string; items: { instrument_key: string; symbol: string; exchange: string; held: boolean; fresh: boolean; period: Period; snapshot: { indicators: Record<string, number | null> } }[] }
type SelectFieldProps = { title: string; value: string; onChange: (value: string) => void; options: [string, string][]; disabled?: boolean }
function SelectField({ title, value, onChange, options, disabled }: SelectFieldProps) {
  return <label className="text-sm space-y-1"><span>{title}</span><Select value={value} onValueChange={onChange} disabled={disabled}>
    <SelectTrigger aria-label={title}><SelectValue /></SelectTrigger><SelectContent>{options.map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent>
  </Select></label>
}
const strategies = ['trend_follow', 'macd_golden', 'volume_breakout', 'momentum', 'pullback', 'rebound']

export default function CryptoOpportunities() {
  const { t } = useTranslation('crypto')
  const { toast } = useToast()
  const [view, setView] = useState<View>()
  const [settings, setSettings] = useState<Settings>()
  const [assets, setAssets] = useState('')
  const [minimum, setMinimum] = useState('70')
  const [filters, setFilters] = useState({ timeframe: '1d', strategy: 'all', holding: 'all', state: 'all', freshness: 'all', risk: 'all', min_score: '70' })
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [fields, setFields] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const initialized = useRef(false)
  const mounted = useRef(true)
  const sequence = useRef(0)
  const query = new URLSearchParams(filters).toString()
  const load = async () => {
    const request = ++sequence.current
    try {
      const next = await fetchAPI<View>(`/crypto/opportunities?${query}`)
      if (!mounted.current || request !== sequence.current) return
      setView(next); setLoadError('')
      if (!initialized.current) { initialized.current = true; setSettings(next.settings); setAssets(next.settings.reviewed_plain_assets.join(', ')) }
    } catch { if (mounted.current && request === sequence.current) setLoadError(t('opportunities.loadFailed')) }
  }
  useEffect(() => {
    mounted.current = true; void load()
    const timer = window.setInterval(() => { void load() }, 5000)
    return () => { mounted.current = false; sequence.current++; window.clearInterval(timer) }
  }, [query, t])
  const running = ['running', 'cancelling'].includes(view?.job.status || '')
  const change = (key: string, value: string) => setFilters(old => ({ ...old, [key]: value }))
  const time = (stamp: number) => new Date(stamp).toLocaleString()
  const invalid = (key: string) => fields.includes(key) ? <p className="text-xs text-destructive">{t(`opportunities.validation.${key}`, { defaultValue: t('opportunities.invalid') })}</p> : null
  const action = async (cancel = false) => {
    if (!settings) return
    const value = { ...settings, reviewed_plain_assets: assets.split(/[,\s]+/).filter(Boolean).map(s => s.toUpperCase()) }
    const invalidFields: string[] = []
    if (!Number.isInteger(value.limit) || value.limit < 1 || value.limit > 10) invalidFields.push('limit')
    if (!validCryptoDecimal(value.min_quote_volume, true)) invalidFields.push('volume')
    if (!validCryptoDecimal(value.max_spread_pct, true) || Number(value.max_spread_pct) > 5) invalidFields.push('spread')
    if (!value.reviewed_plain_assets.length || value.reviewed_plain_assets.length > 100 || new Set(value.reviewed_plain_assets).size !== value.reviewed_plain_assets.length || value.reviewed_plain_assets.some(s => !/^[A-Z0-9][A-Z0-9._-]{0,30}$/.test(s) || ['USD', 'USDT', 'USDC', 'DAI', 'FDUSD', 'USDE', 'TUSD', 'BUSD', 'USDP'].includes(s))) invalidFields.push('assets')
    setFields(cancel ? [] : invalidFields)
    if (!cancel && invalidFields.length) { setError(t('opportunities.invalid')); return }
    setBusy(true)
    try {
      await fetchAPI(`/crypto/opportunities/${cancel ? 'cancel' : 'scans'}`, { method: 'POST', ...(!cancel ? { body: JSON.stringify(value) } : {}) })
      setError(''); toast(t(cancel ? 'opportunities.cancelRequested' : 'opportunities.started'), 'success'); await load()
    } catch { setError(t('opportunities.actionFailed')) }
    finally { if (mounted.current) setBusy(false) }
  }
  return <main className="p-4 sm:p-6 max-w-6xl mx-auto space-y-5">
    <header className="space-y-2"><h1 className="text-2xl font-semibold">{t('opportunities.title')}</h1><p className="text-sm text-muted-foreground">{t('opportunities.description')}</p>
      <div className="flex gap-4 text-sm"><Link className="text-primary underline" to="/crypto">{t('opportunities.holdingsLink')}</Link><Link className="text-primary underline" to="/opportunities">{t('opportunities.stocksLink')}</Link></div>
    </header>
    {(error || loadError) && <p role="alert" className="border border-destructive rounded-xl p-3 text-sm">{error || loadError}</p>}
    {!settings && <p role="status">{t('opportunities.loading')}</p>}
    {settings && <section className="border border-border rounded-2xl bg-card p-4 space-y-3">
      <h2 className="font-semibold">{t('opportunities.scanSettings')}</h2>
      <div className="grid sm:grid-cols-3 gap-3">
        <SelectField title={t('exchange')} value={settings.exchange} disabled={running || busy} onChange={exchange => setSettings({ ...settings, exchange })} options={['binance', 'okx', 'kraken'].map(s => [s, s])} />
        <SelectField title={t('opportunities.quote')} value={settings.quote_currency} disabled={running || busy} onChange={quote_currency => setSettings({ ...settings, quote_currency })} options={['USDT', 'USD'].map(s => [s, s])} />
        <label className="text-sm">{t('opportunities.limit')}<Input aria-invalid={fields.includes('limit')} type="number" min={1} max={10} disabled={running || busy} value={settings.limit} onChange={e => setSettings({ ...settings, limit: Number(e.target.value) })} />{invalid('limit')}</label>
      </div>
      <details><summary className="cursor-pointer text-sm">{t('opportunities.advanced')}</summary><div className="grid sm:grid-cols-2 gap-3 mt-3">
        <label className="text-sm sm:col-span-2">{t('opportunities.assets')}<Input aria-invalid={fields.includes('assets')} value={assets} disabled={running || busy} placeholder="BTC, ETH" onChange={e => setAssets(e.target.value)} />{invalid('assets')}</label>
        <label className="text-sm">{t('opportunities.volume')}<Input aria-invalid={fields.includes('volume')} value={settings.min_quote_volume} disabled={running || busy} inputMode="decimal" onChange={e => setSettings({ ...settings, min_quote_volume: e.target.value })} />{invalid('volume')}</label>
        <label className="text-sm">{t('opportunities.spread')}<Input aria-invalid={fields.includes('spread')} value={settings.max_spread_pct} disabled={running || busy} inputMode="decimal" onChange={e => setSettings({ ...settings, max_spread_pct: e.target.value })} />{invalid('spread')}</label>
      </div></details>
      <p className="text-xs text-muted-foreground">{t('opportunities.settingsHint')}</p>
      <div className="flex flex-wrap gap-2 items-center"><Button disabled={running || busy} onClick={() => { void action() }}>{t('opportunities.scan')}</Button><Button variant="outline" disabled={!running || busy || view?.job.status === 'cancelling'} onClick={() => { void action(true) }}>{t('opportunities.cancel')}</Button><span role="status" className="text-sm">{t(`opportunities.jobs.${view?.job.status || 'empty'}`, { defaultValue: t('opportunities.loading') })}</span></div>
    </section>}
    <section className="border border-border rounded-2xl bg-card p-4 space-y-3">
      <h2 className="font-semibold">{t('opportunities.filters')}</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SelectField title={t('opportunities.timeframe')} value={filters.timeframe} onChange={v => change('timeframe', v)} options={['1d', '1h'].map(s => [s, t(`timeframes.${s}`, { defaultValue: s })])} />
        <SelectField title={t('opportunities.strategy')} value={filters.strategy} onChange={v => change('strategy', v)} options={['all', ...strategies].map(s => [s, t(`opportunities.strategies.${s}`, { defaultValue: s })])} />
        <SelectField title={t('opportunities.holding')} value={filters.holding} onChange={v => change('holding', v)} options={['all', 'held', 'unheld'].map(s => [s, t(`opportunities.holdings.${s}`, { defaultValue: s })])} />
        <SelectField title={t('opportunities.state')} value={filters.state} onChange={v => change('state', v)} options={['all', 'matched', 'watch', 'excluded'].map(s => [s, t(`opportunities.states.${s}`, { defaultValue: s })])} />
        <SelectField title={t('opportunities.freshness')} value={filters.freshness} onChange={v => change('freshness', v)} options={['all', 'current', 'historical'].map(s => [s, t(`opportunities.freshnessOptions.${s}`, { defaultValue: s })])} />
        <SelectField title={t('opportunities.risk')} value={filters.risk} onChange={v => change('risk', v)} options={['all', 'unknown'].map(s => [s, t(`opportunities.risks.${s}`, { defaultValue: s })])} />
        <label className="text-sm">{t('opportunities.minScore')}<Input type="number" min={0} max={100} value={minimum} aria-invalid={!minimum || !Number.isFinite(Number(minimum)) || Number(minimum)<0 || Number(minimum)>100} onChange={e => { const v=e.target.value; setMinimum(v); if (v && Number.isFinite(Number(v)) && Number(v)>=0 && Number(v)<=100) change('min_score', v) }} />{(!minimum || Number(minimum)<0 || Number(minimum)>100) && <p className="text-xs text-destructive">{t('opportunities.validation.minScore')}</p>}</label>
      </div>
    </section>
    <section className="space-y-3">
      <h2 className="font-semibold">{t('opportunities.results')}</h2>
      <p className="text-sm text-muted-foreground">{t('opportunities.counts', { shown: view?.items.length || 0, captured: view?.captured_count || 0, current: view?.current_count || 0, selected: view?.coverage.selected_count || 0, markets: view?.coverage.market_eligible_count || 0 })}</p>
      {view?.asof_ms && <p className="text-xs text-muted-foreground">{t('opportunities.capturedAt')}: {time(view.asof_ms)} · {view.scan_config?.exchange} / {view.scan_config?.quote_currency}</p>}
      <details className="text-sm"><summary className="cursor-pointer">{t('opportunities.coverageDetails')}</summary><p className="text-xs text-muted-foreground my-2">{t('opportunities.reasonHint')}</p><ul className="space-y-1">{Object.entries(view?.exclusions || {}).map(([reason, count]) => <li key={reason}>{t(`opportunities.exclusions.${reason}`, { defaultValue: t('opportunities.otherReason') })}: {count}</li>)}</ul></details>
      {!view?.items.length && <p className="border border-border rounded-xl p-4 text-sm">{t('opportunities.empty')}</p>}
      <div className="grid sm:grid-cols-2 gap-3">{view?.items.map(item => <article key={item.instrument_key} className="border border-border rounded-xl bg-card p-4 space-y-2 min-w-0">
        <div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold">{item.symbol} · {item.exchange}</h3><span>{item.period.technical_score.toFixed(1)}</span></div>
        <p className="text-sm">{t(`opportunities.states.${item.period.state}`, { defaultValue: item.period.state })} · {t(`opportunities.holdings.${item.held ? 'held' : 'unheld'}`)} · {t(`opportunities.freshnessOptions.${item.fresh ? 'current' : 'historical'}`)}</p>
        <p className="text-sm">{item.period.strategy_labels.length ? item.period.strategy_tags.map(tag => t(`opportunities.strategies.${tag}`, { defaultValue: tag })).join(' / ') : t('opportunities.noTags')}</p>
        <details><summary className="cursor-pointer text-sm text-primary">{t('opportunities.evidence')}</summary><div className="space-y-2 text-xs mt-2 break-words">
          <p>{t('candleClose')}: {time(item.period.source_close_ms)}</p>
          <dl>{['ma20', 'rsi6', 'macd_hist', 'atr'].map(key => <div className="flex justify-between gap-2" key={key}><dt>{t(`indicatorLabels.${key}`, { defaultValue: key })}</dt><dd className="font-mono break-all">{item.snapshot.indicators[key]?.toLocaleString(undefined, { maximumSignificantDigits: 8 }) ?? '—'}</dd></div>)}</dl>
          <p className="break-all">{t('opportunities.snapshot')}: {item.period.snapshot_id}</p><p className="break-all">{item.period.profile_version} · {item.period.rules_version}</p>
        </div></details>
      </article>)}</div>
    </section>
  </main>
}
