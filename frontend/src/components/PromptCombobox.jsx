import { useMemo } from 'react'
import Combobox from './Combobox'

export const NEW_PROMPT = 'new'

// Picker for a saved grading prompt. value is NEW_PROMPT or a prompt id.
// "New prompt" is always the first option and stays visible while filtering.
export default function PromptCombobox({ prompts, value, onChange }) {
  const options = useMemo(
    () => [
      { value: NEW_PROMPT, label: 'New prompt', pinned: true, emphasis: true, asPlaceholder: true },
      ...prompts.map((p) => ({ value: p.id, label: p.name })),
    ],
    [prompts]
  )

  return (
    <Combobox
      options={options}
      value={value}
      onChange={onChange}
      placeholder="Choose a prompt or type to search"
      emptyText="No saved prompts match."
    />
  )
}
