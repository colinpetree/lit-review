// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// The layout's own job here is the "not connected" banner; its children have their own tests.
vi.mock('./UpdateProvider', () => ({ UpdateProvider: ({ children }) => children, useUpdates: () => ({}) }))
vi.mock('./JobsProvider', () => ({ JobsProvider: ({ children }) => children }))
vi.mock('./SettingsModalProvider', () => ({ SettingsModalProvider: ({ children }) => children }))
vi.mock('./Sidebar', () => ({ default: () => null }))
vi.mock('./UpdateBanner', () => ({ default: () => null }))
vi.mock('./UpdateModal', () => ({ default: () => null }))
// jsdom has no matchMedia, which the theme hook asks about the system's light or dark setting.
window.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {} })

import AppLayout from './AppLayout'
import { NOT_CONNECTED_MESSAGE, reportConnected, reportNotConnected } from '../lib/session'

afterEach(() => {
  cleanup()
  reportConnected()
})

describe('the not-connected banner', () => {
  it('appears on any refusal (401), with the words the server uses, and goes when a call works', () => {
    render(
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('alert')).toBeNull()
    act(() => reportNotConnected())
    expect(screen.getByRole('alert').textContent).toBe(NOT_CONNECTED_MESSAGE)
    act(() => reportConnected())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
