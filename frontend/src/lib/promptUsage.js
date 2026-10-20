// The prompts that graded a set of evaluations (one dataset's), one entry per prompt, most recently
// used first. `livePrompts` is GET /api/prompts: a prompt not in it is in Deleted Items, so it is
// marked `deleted` (no page to link to) and its example count is unknown.
export function promptsUsedBy(runs, livePrompts) {
  const live = new Map((livePrompts ?? []).map((p) => [p.id, p]))
  const byId = new Map()
  for (const run of runs) {
    // Every run has a prompt, but old rows were backfilled, so one without is skipped, not shown blank.
    if (run.prompt_id == null) continue
    const used = run.completed_at || run.created_at
    const entry = byId.get(run.prompt_id)
    if (entry) {
      entry.evaluations += 1
      if (used > entry.lastUsed) entry.lastUsed = used
      continue
    }
    const prompt = live.get(run.prompt_id)
    byId.set(run.prompt_id, {
      id: run.prompt_id,
      name: prompt?.name ?? run.prompt_name ?? run.grading_prompt,
      deleted: !prompt,
      examples: prompt ? prompt.example_count : null,
      evaluations: 1,
      lastUsed: used,
    })
  }
  return [...byId.values()].sort((a, b) => (a.lastUsed < b.lastUsed ? 1 : a.lastUsed > b.lastUsed ? -1 : 0))
}
