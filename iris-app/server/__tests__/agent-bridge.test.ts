import { describe, it, expect } from 'vitest'
import { buildDialsBlock, extractYamlSubmap } from '../agent-bridge.js'

function cfg(autonomy: string, statistical: string, methodological: string, interpretive: string): string {
  return `name: demo\nautonomy: ${autonomy}\npushback:\n  statistical: ${statistical}\n  methodological: ${methodological}\n  interpretive: ${interpretive}\n`
}

describe('extractYamlSubmap', () => {
  it('parses a nested mapping block', () => {
    const got = extractYamlSubmap(cfg('high', 'rigorous', 'balanced', 'light'), 'pushback')
    expect(got).toEqual({ statistical: 'rigorous', methodological: 'balanced', interpretive: 'light' })
  })

  it('returns empty object when parent key is absent', () => {
    expect(extractYamlSubmap('autonomy: medium\n', 'pushback')).toEqual({})
  })

  it('strips inline comments', () => {
    const src = 'pushback:\n  statistical: rigorous   # strongest\n  methodological: light\n'
    expect(extractYamlSubmap(src, 'pushback')).toEqual({ statistical: 'rigorous', methodological: 'light' })
  })
})

describe('buildDialsBlock', () => {
  it('maps rigorous statistical pushback to refusal language', () => {
    const out = buildDialsBlock(cfg('medium', 'rigorous', 'balanced', 'light'))
    expect(out).toContain('statistical: rigorous — refuse to run until the user acknowledges')
    expect(out).toContain('methodological: balanced — flag the concern, propose alternatives, and ask the user to choose')
    expect(out).toContain('interpretive: light — note the concern in a single sentence, then implement anyway')
  })

  it('emits the full autonomy=low rubric', () => {
    const out = buildDialsBlock(cfg('low', 'balanced', 'balanced', 'balanced'))
    expect(out).toContain('autonomy=low')
    expect(out).toContain('Only free reads')
    expect(out).toContain('Every op run, every plot, every L3 write must be proposed')
  })

  it('emits the autonomy=high rubric with re-execution allowance', () => {
    const out = buildDialsBlock(cfg('high', 'light', 'light', 'light'))
    expect(out).toContain('autonomy=high')
    expect(out).toContain('re-execution of ops already run')
    expect(out).toContain('Novel analyses, new op definitions')
  })

  it('emits the autonomy=medium rubric when the value is absent', () => {
    const out = buildDialsBlock('name: demo\n')
    expect(out).toContain('autonomy=medium')
    // Missing pushback entries default to balanced.
    expect(out).toContain('statistical: balanced')
    expect(out).toContain('methodological: balanced')
    expect(out).toContain('interpretive: balanced')
  })

  it('names the three pushback domain scopes verbatim', () => {
    const out = buildDialsBlock(cfg('medium', 'balanced', 'balanced', 'balanced'))
    expect(out).toContain('Scope: assumption violations')
    expect(out).toContain('Scope: pipeline ordering')
    expect(out).toContain('Scope: causal vs. correlational')
  })

  it('notes that L0/L1 writes are never gated by autonomy', () => {
    const out = buildDialsBlock(cfg('low', 'balanced', 'balanced', 'balanced'))
    expect(out).toContain('L0 (conversation) and L1 (event ledger) writes are never gated')
  })
})
