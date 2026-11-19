// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Cell, DataTable, ListRow, MenuCell } from './ListTable'

afterEach(cleanup)

const columns = [{ label: 'Name' }, { label: '' }]

function renderTable(onMenu) {
  render(
    <MemoryRouter initialEntries={['/datasets']}>
      <Routes>
        <Route
          path="/datasets"
          element={
            <DataTable columns={columns}>
              <ListRow to="/datasets/7">
                <Cell column={columns[0]}>Graphene thermal transport</Cell>
                <MenuCell column={columns[1]}>
                  <button type="button" onClick={onMenu}>
                    More actions
                  </button>
                  <div role="dialog">A modal opened from the menu</div>
                </MenuCell>
              </ListRow>
            </DataTable>
          }
        />
        <Route path="/datasets/7" element={<p>Dataset page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('list table rows', () => {
  it('a click anywhere on a row opens it', () => {
    renderTable(vi.fn())
    fireEvent.click(screen.getByText('Graphene thermal transport'))
    expect(screen.getByText('Dataset page')).toBeTruthy()
  })

  it('the row menu, and anything opened from it, never opens the row', () => {
    const onMenu = vi.fn()
    renderTable(onMenu)
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByText('A modal opened from the menu'))
    expect(onMenu).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Dataset page')).toBeNull()
  })

  it('draws nothing while there are no rows', () => {
    const { container } = render(<DataTable columns={columns}>{[]}</DataTable>)
    expect(container.innerHTML).toBe('')
  })
})
