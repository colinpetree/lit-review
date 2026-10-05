// How many items a long list renders at first, and how many more each scroll adds.
export const PAGE_SIZE = 20

// How many items to show now. The count belongs to one `resetKey` (a different
// filter, sort or page starts again at one page); `state` is { key, count }.
export function shownCount(state, resetKey, pageSize = PAGE_SIZE) {
  return state.key === resetKey ? state.count : pageSize
}

// The state after asking for one more page.
export function showMore(state, resetKey, pageSize = PAGE_SIZE) {
  return { key: resetKey, count: shownCount(state, resetKey, pageSize) + pageSize }
}
