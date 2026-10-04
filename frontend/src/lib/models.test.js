import { describe, expect, it } from 'vitest'
import { modelNameList } from './models'

describe('modelNameList', () => {
  it('lists three models with commas and a final "and"', () => {
    expect(modelNameList('anthropic')).toBe('Claude Haiku 4.5, Claude Sonnet 5, and Claude Opus 5')
  })

  it('has nothing to say about a provider it does not know', () => {
    expect(modelNameList('nobody')).toBe('')
  })
})
