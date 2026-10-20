import { Link } from 'react-router-dom'
import { JobStatusDot } from './JobStatus'
import InfiniteList from './InfiniteList'
import RunMenu from './RunMenu'
import ModelBadge from './ModelBadge'
import { Cell, DataTable, ListRow, MenuCell, TruncatedText } from './ListTable'
import { Tooltip } from './ui/Tooltip'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'

const COLUMNS = [
  { label: 'Name' },
  { label: 'Datasets' },
  { label: 'Papers' },
  { label: 'Date' },
  { label: 'AI model' },
  { label: 'Est. cost' },
  { label: '' },
]

// Module level so React keeps one component (and the table) across renders.
const RunsTable = (props) => <DataTable columns={COLUMNS} {...props} />

// The evaluations table: the Paper Evaluations list's table view, and the Evaluations tab on a
// dataset or prompt page. `compact` cuts the long Name and Datasets text shorter, for a page in
// the narrow column. `onRenamed(id, name)` and `onDelete(id)` are the row menu's.
export default function RunsTableList({ runs, resetKey, compact = false, onRenamed, onDelete, onError }) {
  return (
    <InfiniteList
      as={RunsTable}
      items={runs}
      resetKey={resetKey}
      renderItem={(run) => {
        const [name, datasets, papers, date, model, cost, menu] = COLUMNS
        const title = run.name || run.prompt_name || run.grading_prompt
        const datasetText = datasetLabels(run.datasets).join(', ')
        return (
          <ListRow key={run.id} to={`/evaluations/${run.id}`}>
            <Cell column={name}>
              <div className="flex items-center gap-2">
                <JobStatusDot item={run} />
                <Tooltip content="View details">
                  <Link
                    to={`/evaluations/${run.id}`}
                    className={`block truncate font-medium text-gray-800 hover:underline ${compact ? 'max-w-[14rem]' : 'max-w-xs'}`}
                  >
                    {title}
                  </Link>
                </Tooltip>
              </div>
            </Cell>
            <Cell column={datasets}>
              <TruncatedText text={datasetText} className={`text-gray-500 ${compact ? 'max-w-[12rem]' : 'max-w-md'}`} />
            </Cell>
            <Cell column={papers} className="text-gray-600">{run.paper_count}</Cell>
            <Cell column={date} className="text-gray-600">{formatDateTime(run.completed_at || run.created_at)}</Cell>
            <Cell column={model}>
              <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} className="text-sm text-gray-600" />
            </Cell>
            <Cell column={cost} className="text-gray-600">
              {run.cost != null ? <span title={RUN_COST_NOTE}>${run.cost.toFixed(2)}</span> : null}
            </Cell>
            <MenuCell column={menu}>
              <RunMenu
                floating
                run={run}
                onRenamed={(n) => onRenamed(run.id, n)}
                onDelete={() => onDelete(run.id)}
                onError={onError}
              />
            </MenuCell>
          </ListRow>
        )
      }}
    />
  )
}
