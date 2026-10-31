import { expect, it } from 'vitest'
import { changeCryptoPair, validCryptoDecimal, validateCryptoForm } from '@/lib/crypto-form'

it('bounds exact decimals without float conversion', () => {
  for (const value of ['0', '0.000000000000000001', '1e-24', '999999999999999999999', '0.12345678901234567890123456789012']) expect(validCryptoDecimal(value)).toBe(true)
  for (const value of ['USDT', '-1', 'NaN', 'Infinity', '1,000', '1e-25', '1e21', '1.12345678901234567890123456789012']) expect(validCryptoDecimal(value)).toBe(false)
  expect(validCryptoDecimal('0', true)).toBe(false)
})

it('updates linked threshold drafts while retaining decimal strings', () => {
  const config = { exchange:'okx', interval_seconds:60, positions:[{symbol:'BTC/USDT',quantity:'0.000000000000000001'}], alerts:[{symbol:'BTC/USDT',op:'>=' as const,price:'79000',cooldown_minutes:60,notify:false}] }
  const changed = changeCryptoPair(config, 0, 'ETH/USDT')
  expect(changed.alerts[0].symbol).toBe('ETH/USDT')
  expect(changed.positions[0].quantity).toBe(config.positions[0].quantity)
  expect(validateCryptoForm(changed)).toEqual({})
  expect(config.alerts[0].symbol).toBe('BTC/USDT')
})
