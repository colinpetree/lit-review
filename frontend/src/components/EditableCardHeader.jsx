// The Edit/Cancel/Save button chrome shared by every settings card - matches
// an earlier project's admin EditableCard header exactly (button classes, the
// #30cf43 green, the transient "Saved" state on the Edit button).
export default function EditableCardHeader({
  title,
  icon: Icon,
  description,
  linkUrl,
  linkLabel,
  editing,
  saving,
  saved,
  isDirty,
  onEdit,
  onCancel,
  onSave,
  saveLabel = 'Save',
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-800 [--icon-nudge:-1px]">
          {Icon ? <Icon size={18} className="shrink-0" /> : null}
          {title}
        </h2>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
        {linkUrl && (
          <a
            href={linkUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-xs text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline"
          >
            {linkLabel}
          </a>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {!editing && (
          <button
            onClick={() => !saved && onEdit()}
            disabled={saved}
            className="rounded-md bg-white px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-default text-gray-400 enabled:text-gray-700 enabled:hover:bg-gray-50"
          >
            {saved ? 'Saved' : 'Edit'}
          </button>
        )}
        {editing && (
          <>
            {!saving && (
              <button
                onClick={onCancel}
                className="rounded-md px-3 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              onClick={onSave}
              disabled={!isDirty || saving}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                saving
                  ? 'bg-white text-gray-500 cursor-default'
                  : isDirty
                    ? 'bg-[#30cf43] text-white hover:brightness-95'
                    : 'bg-gray-100 text-gray-400 cursor-default'
              }`}
            >
              {saving ? 'Saving...' : saveLabel}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
