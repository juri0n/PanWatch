export type CryptoPosition = { symbol: string; quantity: string }
export type CryptoRule = { symbol: string; op: '>=' | '<='; price: string; cooldown_minutes: number; notify: boolean }
export type CryptoConfig = { exchange: string; interval_seconds: number; positions: CryptoPosition[]; alerts: CryptoRule[] }
export type CryptoFieldError = 'pair' | 'quantity' | 'duplicatePair' | 'interval' | 'price' | 'alertPair' | 'cooldown' | 'duplicateThreshold'

// Match the server Decimal bounds without converting the user's quantity to Number.
export function validCryptoDecimal(value: string, positive = false): boolean {
  const match = /^\+?(\d+(?:\.\d*)?|\.\d+)(?:e([+-]?\d+))?$/i.exec(value.trim())
  if (!match || value.length > 256) return false
  const coefficient = match[1]
  const digits = coefficient.replace('.', '').replace(/^0+/, '') || '0'
  const exponent = Number(match[2] || '0') - (coefficient.split('.')[1]?.length || 0)
  const adjusted = exponent + digits.length - 1
  return digits.length <= 32 && exponent >= -64 && exponent <= 20
    && (digits === '0' ? !positive : adjusted >= -24 && adjusted <= 20)
}

export function normalizedCryptoConfig(config: CryptoConfig): CryptoConfig {
  return { ...config, positions: config.positions.map(p => ({ symbol: p.symbol.trim().toUpperCase(), quantity: p.quantity.trim() })),
    alerts: config.alerts.map(r => ({ ...r, symbol: r.symbol.trim().toUpperCase(), price: r.price.trim() })) }
}

export function validateCryptoForm(config: CryptoConfig): Record<string, CryptoFieldError> {
  const errors: Record<string, CryptoFieldError> = {}
  if (!Number.isInteger(config.interval_seconds) || config.interval_seconds < 60 || config.interval_seconds > 3600) errors.interval_seconds = 'interval'
  const symbols = new Set<string>()
  config.positions.forEach((position, i) => {
    if (!/^[A-Z0-9][A-Z0-9._-]*\/(USD|USDT)$/.test(position.symbol)) errors[`positions.${i}.symbol`] = 'pair'
    else if (symbols.has(position.symbol)) errors[`positions.${i}.symbol`] = 'duplicatePair'
    symbols.add(position.symbol)
    if (!validCryptoDecimal(position.quantity)) errors[`positions.${i}.quantity`] = 'quantity'
  })
  const thresholds = new Set<string>()
  config.alerts.forEach((rule, i) => {
    if (!symbols.has(rule.symbol)) errors[`alerts.${i}.symbol`] = 'alertPair'
    if (!validCryptoDecimal(rule.price, true)) errors[`alerts.${i}.price`] = 'price'
    if (!Number.isInteger(rule.cooldown_minutes) || rule.cooldown_minutes < 1 || rule.cooldown_minutes > 10080) errors[`alerts.${i}.cooldown_minutes`] = 'cooldown'
    const key = JSON.stringify([rule.symbol, rule.op])
    if (thresholds.has(key)) errors[`alerts.${i}.op`] = 'duplicateThreshold'
    thresholds.add(key)
  })
  return errors
}

export function changeCryptoPair(config: CryptoConfig, index: number, symbol: string): CryptoConfig {
  const old = config.positions[index].symbol
  return { ...config, positions: config.positions.map((p, i) => i === index ? { ...p, symbol } : p),
    alerts: config.alerts.map(r => r.symbol === old ? { ...r, symbol } : r) }
}
