// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import Modal from './Modal'
import ConfirmModal from './ConfirmModal'

afterEach(cleanup)

const backdrop = () => screen.getByRole('dialog').parentElement
const clickBackdrop = () => {
  fireEvent.mouseDown(backdrop())
  fireEvent.click(backdrop())
}

describe('Modal', () => {
  it('closes on Escape, the X and a click outside', () => {
    const onClose = vi.fn()
    render(<Modal title="T" onClose={onClose}>body</Modal>)
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    clickBackdrop()
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  it('does not close when a drag that started inside the dialog ends outside it', () => {
    const onClose = vi.fn()
    render(<Modal title="T" onClose={onClose}>body</Modal>)
    fireEvent.mouseDown(screen.getByRole('dialog'))
    fireEvent.click(backdrop())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps a form open: no closing on a click outside or Escape when asked', () => {
    const onClose = vi.fn()
    render(
      <Modal title="T" onClose={onClose} closeOnBackdrop={false} closeOnEscape={false}>
        body
      </Modal>,
    )
    clickBackdrop()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('cannot be dismissed while busy', () => {
    const onClose = vi.fn()
    render(
      <Modal title="T" onClose={onClose} busy>
        body
      </Modal>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    clickBackdrop()
    expect(screen.getByRole('button', { name: 'Close' }).disabled).toBe(true)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Escape closes only the dialog on top', () => {
    const outer = vi.fn()
    const inner = vi.fn()
    render(
      <>
        <Modal title="Outer" onClose={outer}>
          a
        </Modal>
        <Modal title="Inner" onClose={inner}>
          b
        </Modal>
      </>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(inner).toHaveBeenCalledTimes(1)
    expect(outer).not.toHaveBeenCalled()
  })
})

describe('ConfirmModal', () => {
  it('closes after the action succeeds', async () => {
    const onClose = vi.fn()
    const onConfirm = vi.fn().mockResolvedValue()
    render(<ConfirmModal title="Delete?" message="Sure?" confirmLabel="Delete" onConfirm={onConfirm} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('stays open and shows why when the action fails, so it can be tried again', async () => {
    const onClose = vi.fn()
    const onConfirm = vi.fn().mockRejectedValueOnce(new Error('The server said no.')).mockResolvedValueOnce()
    render(<ConfirmModal title="Delete?" message="Sure?" confirmLabel="Delete" onConfirm={onConfirm} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('The server said no.')).toBeTruthy()
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })
})
