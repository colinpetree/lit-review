import { useCallback, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { SETTINGS_ITEM, SETTINGS_NAV } from '../lib/navItems'
import { Tooltip } from './ui/Tooltip'
import useCollapsedNav from '../lib/useCollapsedNav'
import AiIntegrationsSection from './settings/AiIntegrationsSection'
import ResearchDatabasesSection from './settings/ResearchDatabasesSection'
import YourDataSection from './settings/YourDataSection'
import AppearanceSection from './settings/AppearanceSection'
import AboutSection from './settings/AboutSection'
import LicenseSection from './settings/LicenseSection'

// Keyed by the ids in SETTINGS_NAV, which also sets the order they appear in.
const SECTIONS = {
  ai: AiIntegrationsSection,
  databases: ResearchDatabasesSection,
  data: YourDataSection,
  appearance: AppearanceSection,
  about: AboutSection,
  license: LicenseSection,
}

// The gap kept above a section's title when a link scrolls to it, and above the first section
// (the pt-16 on the page, below). The gap around each divider is larger (my-24 on the <hr>).
const SECTION_GAP = 64
// How far below the top edge a section's title counts as the one being read.
const READING_LINE = SECTION_GAP + 32

// Settings as one long scrolling page in a large dialog over the app, so it can't be
// mistaken for an app page. The list on the left scrolls to a section and follows the scroll.
export default function SettingsModal({ section, onClose }) {
  const [active, setActive] = useState(section)
  const scrollRef = useRef(null)
  const dialogRef = useRef(null)
  const pressStartedOnBackdrop = useRef(false)
  const collapsed = useCollapsedNav()
  // Names show as tooltips only while the labels are hidden.
  const tip = (label) => (collapsed ? label : null)

  // Where a section starts, in the scroll area's own coordinates.
  const sectionTop = (id) => {
    const el = document.getElementById(`settings-${id}`)
    const box = scrollRef.current
    return el && box ? el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop : 0
  }

  // Opens at the section asked for, with no animation.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: sectionTop(section) - SECTION_GAP })
    dialogRef.current?.focus()
  }, [section])

  useEffect(() => {
    const onKey = (e) => {
      // A dialog opened from inside Settings (a confirmation, the license) takes Escape first.
      if (e.key === 'Escape' && document.querySelectorAll('[role="dialog"]').length === 1) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const onScroll = useCallback(() => {
    const box = scrollRef.current
    if (!box) return
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 2
    let current = SETTINGS_NAV[0].id
    for (const { id } of SETTINGS_NAV) {
      if (sectionTop(id) - box.scrollTop <= READING_LINE) current = id
    }
    setActive(atBottom ? SETTINGS_NAV[SETTINGS_NAV.length - 1].id : current)
  }, [])

  const goTo = (id) => {
    setActive(id)
    scrollRef.current?.scrollTo({ top: sectionTop(id) - SECTION_GAP, behavior: 'smooth' })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 sm:px-[5vw] sm:py-[5vh]"
      onMouseDown={(e) => {
        pressStartedOnBackdrop.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (pressStartedOnBackdrop.current && e.target === e.currentTarget) onClose()
        pressStartedOnBackdrop.current = false
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        tabIndex={-1}
        className="relative flex h-full w-full max-w-6xl overflow-hidden rounded-lg bg-surface shadow-xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <nav
          aria-label="Settings sections"
          className="flex w-14 shrink-0 flex-col gap-1 overflow-y-auto overflow-x-hidden border-r border-gray-200 bg-sidebar px-2 py-5 lg:w-56 lg:px-3"
        >
          <Tooltip content={tip(SETTINGS_ITEM.label)} side="right">
            <div className="flex items-center justify-center gap-2.5 pb-3 text-sm font-semibold text-stone-700 lg:justify-start lg:px-3">
              <SETTINGS_ITEM.icon size={16} className="shrink-0" />
              <span className="hidden lg:inline">{SETTINGS_ITEM.label}</span>
            </div>
          </Tooltip>
          {SETTINGS_NAV.map((item) => (
            <Tooltip key={item.id} content={tip(item.label)} side="right">
              <button
                type="button"
                onClick={() => goTo(item.id)}
                aria-label={item.label}
                aria-current={active === item.id ? 'true' : undefined}
                className={`flex h-9 w-9 mx-auto items-center justify-center gap-2.5 rounded-md text-sm transition-colors lg:h-auto lg:w-full lg:justify-start lg:px-3 lg:py-2 lg:text-left ${
                  active === item.id
                    ? 'bg-stone-200 font-medium text-stone-700'
                    : 'text-stone-500 hover:bg-stone-200/60 hover:text-stone-700'
                }`}
              >
                <item.icon size={16} className="shrink-0" />
                <span className="hidden lg:inline">{item.label}</span>
              </button>
            </Tooltip>
          ))}
        </nav>

        <div ref={scrollRef} onScroll={onScroll} className="relative flex-1 overflow-y-auto [container-type:size]">
          <div className="mx-auto max-w-3xl px-10 pb-16 pt-16">
            {SETTINGS_NAV.map((item, i) => {
              const Section = SECTIONS[item.id]
              return (
                // The last section is at least as tall as the dialog (less the gap above its title), so it
                // can scroll up to the same spot as the others in a window of any height.
                <div
                  key={item.id}
                  style={i === SETTINGS_NAV.length - 1 ? { minHeight: `calc(100cqh - ${SECTION_GAP}px)` } : undefined}
                >
                  {i > 0 ? <hr className="my-24 border-t border-gray-200" /> : null}
                  <Section />
                </div>
              )
            })}
          </div>
        </div>

        <button
          type="button"
          aria-label="Close settings"
          onClick={onClose}
          className="absolute right-4 top-4 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  )
}
