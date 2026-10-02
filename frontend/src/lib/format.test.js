import { describe, expect, it } from 'vitest'
import { isHttpUrl } from './format'

describe('isHttpUrl', () => {
  it.each(['https://doi.org/10.1/x', 'http://example.com', 'HTTPS://EXAMPLE.COM/a?b=c'])('accepts %s', (url) => {
    expect(isHttpUrl(url)).toBe(true)
  })

  it.each([
    'javascript:alert(1)',
    ' javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'ftp://example.com/file',
    '//example.com',
    'https://',
    'example.com',
    '',
    null,
    undefined,
    42,
  ])('rejects %s', (url) => {
    expect(isHttpUrl(url)).toBe(false)
  })
})
