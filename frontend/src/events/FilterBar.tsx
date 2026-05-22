import { useRef, useState, useEffect, useCallback } from 'react'
import type { FilterState } from './types'

const CATS = [
  { id: '', label: 'All' },
  { id: 'music', label: '🎵 Music' },
  { id: 'arts', label: '🎨 Arts' },
  { id: 'bike', label: '🚲 Bike' },
  { id: 'food', label: '🍴 Food' },
  { id: 'fund', label: '💙 Fundraiser' },
  { id: 'hybrid', label: '⚡ Hybrid' },
]

const DATES = [
  { id: '', label: 'All dates' },
  { id: 'today', label: 'Today' },
  { id: 'tomorrow', label: 'Tomorrow' },
  { id: 'weekend', label: 'Weekend' },
]

const VIEWS = [
  { id: 'list',   label: '≡ List' },
  { id: 'map',    label: '⊙ Map' },
  { id: 'hybrid', label: '⊟ Hybrid' },
  { id: 'car',    label: '🚗 Car' },
]

interface Props {
  filters: FilterState
  neighborhoods: string[]
  count: number
  total: number
  hasActive: boolean
  onPatch: (p: Partial<FilterState>) => void
  onClear: () => void
}

export function FilterBar({ filters, neighborhoods, count, total, hasActive, onPatch, onClear }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [showControls, setShowControls] = useState(true)
  const searchRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const idleRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Reset 30s idle timer — opens controls and restarts countdown
  const touch = useCallback(() => {
    clearTimeout(idleRef.current)
    setShowControls(true)
    idleRef.current = setTimeout(() => setShowControls(false), 30_000)
  }, [])

  useEffect(() => {
    touch()
    return () => clearTimeout(idleRef.current)
  }, [touch])

  useEffect(() => {
    if (!showControls) setExpanded(false)
  }, [showControls])

  const patchAndTouch = useCallback((p: Partial<FilterState>) => {
    touch()
    onPatch(p)
  }, [touch, onPatch])

  const handleSearch = useCallback((val: string) => {
    touch()
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onPatch({ search: val }), 180)
  }, [onPatch, touch])

  useEffect(() => () => {
    clearTimeout(timerRef.current as ReturnType<typeof setTimeout>)
  }, [])

  // keyboard shortcuts
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        searchRef.current?.blur()
        setExpanded(false)
      }
    }
    document.addEventListener('keydown', fn)
    return () => document.removeEventListener('keydown', fn)
  }, [touch])

  // Track active view from body class (set by vanilla setView() in event_list.html)
  const [activeView, setActiveView] = useState(() => {
    const m = document.body.className.match(/\bview-(\w+)\b/)
    return m ? m[1] : 'list'
  })
  useEffect(() => {
    const obs = new MutationObserver(() => {
      const m = document.body.className.match(/\bview-(\w+)\b/)
      if (m) setActiveView(m[1])
    })
    obs.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])

  return (
    <div className="fb-root">
      {/* Mobile only — hidden on desktop by event_list.html inline CSS media query */}
      <div className="fb-search-row">
        <div className="fb-search-wrap">
          <span className="fb-search-icon">⌕</span>
          <input
            ref={searchRef}
            className="fb-search"
            type="search"
            placeholder="Search events, artists, venues…"
            defaultValue={filters.search}
            onFocus={touch}
            onChange={e => handleSearch(e.target.value)}
          />
          {filters.search && (
            <button className="fb-search-clear" onClick={() => {
              touch()
              onPatch({ search: '' })
              if (searchRef.current) searchRef.current.value = ''
            }}>✕</button>
          )}
        </div>
      </div>

      {/* Filter controls — open until 30s idle, then slide up */}
      <div className={`fb-controls ${showControls ? 'open' : ''}`}>

        {/* Category pills + filter toggle */}
        <div className="fb-cats">
          {CATS.map(c => (
            <button
              key={c.id}
              className={`fb-cat-pill ${filters.category === c.id ? 'active' : ''}`}
              onClick={() => patchAndTouch({ category: c.id })}
            >
              {c.label}
            </button>
          ))}

          <button
            className={`fb-cat-pill fb-filter-pill ${expanded ? 'active' : ''} ${hasActive && !expanded ? 'has-active' : ''}`}
            onClick={() => { touch(); setExpanded(x => !x) }}
            aria-label="More filters"
          >
            Filters {hasActive && !expanded && <span className="fb-dot" />}
          </button>
        </div>

        {/* Expanded filters */}
        <div className={`fb-expanded ${expanded ? 'open' : ''}`}>
          <div className="fb-expanded-inner">
            <div className="fb-row">
              <span className="fb-label">When</span>
              <div className="fb-pill-group">
                {DATES.map(d => (
                  <button
                    key={d.id}
                    className={`fb-pill ${filters.date === d.id ? 'active' : ''}`}
                    onClick={() => patchAndTouch({ date: d.id })}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            {neighborhoods.length > 0 && (
              <div className="fb-row">
                <span className="fb-label">Hood</span>
                <select
                  className="fb-select"
                  value={filters.neighborhood}
                  onChange={e => patchAndTouch({ neighborhood: e.target.value })}
                >
                  <option value="">Any neighborhood</option>
                  {neighborhoods.map(n => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="fb-row fb-row-bottom">
              <label className="fb-free-toggle">
                <input
                  type="checkbox"
                  checked={filters.free}
                  onChange={e => patchAndTouch({ free: e.target.checked })}
                />
                <span className="fb-toggle-track">
                  <span className="fb-toggle-thumb" />
                </span>
                Free only
              </label>
              {hasActive && (
                <button className="fb-clear" onClick={() => { touch(); onClear(); setExpanded(false) }}>
                  Clear all
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Result count */}
      {hasActive && (
        <div className="fb-count">
          {count === total
            ? `${total} events`
            : `${count} of ${total} events`}
        </div>
      )}

      {/* View switcher — only rendered on mobile via CSS (desktop uses .view-float) */}
      <div className="fb-view-bar">
        {VIEWS.map(v => (
          <button
            key={v.id}
            className={`fb-view-btn${activeView === v.id ? ' active' : ''}`}
            onClick={() => { touch(); (window as any).setView?.(v.id) }}
          >
            {v.label}
          </button>
        ))}
      </div>
    </div>
  )
}
