// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

const updates = vi.hoisted(() => ({ current: {} }))
vi.mock('./UpdateProvider', () => ({ useUpdates: () => updates.current }))

import UpdateModal from './UpdateModal'

afterEach(cleanup)

function withState(state) {
  updates.current = {
    status: { state: 'staged', latest: '0.1.4', current: '0.1.3', auto_apply: false },
    installing: false,
    installError: null,
    modalOpen: false,
    install: vi.fn(),
    closeModal: vi.fn(),
    welcomeVersion: null,
    closeWelcome: vi.fn(),
    stuck: false,
    updated: false,
    closeUpdated: vi.fn(),
    ...state,
  }
  render(<UpdateModal />)
  return updates.current
}

describe('UpdateModal', () => {
  it('shows nothing unless there is something to say', () => {
    withState({})
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('offers a downloaded update: Install update, or Not now', () => {
    const state = withState({ modalOpen: true })
    expect(screen.getByRole('dialog').textContent).toContain('(0.1.4)')
    fireEvent.click(screen.getByRole('button', { name: 'Install update' }))
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(state.install).toHaveBeenCalledTimes(1)
    expect(state.closeModal).toHaveBeenCalledTimes(1)
  })

  it('says why an install could not start', () => {
    withState({ modalOpen: true, installError: 'Something is still running.' })
    expect(screen.getByRole('alert').textContent).toBe('Something is still running.')
  })

  it('cannot be dismissed while installing, until it has taken too long', () => {
    withState({ modalOpen: true, installing: true })
    expect(screen.getByRole('button', { name: 'Close' }).disabled).toBe(true)
    cleanup()
    withState({ modalOpen: true, installing: true, stuck: true })
    expect(screen.getByRole('button', { name: 'Close' }).disabled).toBe(false)
    expect(screen.getByRole('status').textContent).toContain('taking longer than expected')
  })

  it('welcomes the new version first, whatever else is pending', () => {
    const state = withState({ welcomeVersion: '0.1.4', modalOpen: true })
    expect(screen.getByRole('dialog').textContent).toContain('Welcome to Lit Review 0.1.4')
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(state.closeWelcome).toHaveBeenCalledTimes(1)
  })

  it('tells the tab that watched an install how it ended', () => {
    withState({ updated: true, status: { state: 'idle', current: '0.1.4' } })
    expect(screen.getByRole('dialog').textContent).toContain('Lit Review was updated')
    cleanup()
    withState({ updated: true, status: { state: 'failed', current: '0.1.3', error: 'The swap failed.' } })
    expect(screen.getByRole('dialog').textContent).toContain('The update was not installed')
    expect(screen.getByRole('status').textContent).toBe('The swap failed.')
  })
})
