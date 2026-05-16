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
  const [searchFocused, setSearchFocused] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const blurRef  = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleSearch = useCallback((val: string) => {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onPatch({ search: val }), 180)
  }, [onPatch])

  const openControls  = useCallback(() => { clearTimeout(blurRef.current); setSearchFocused(true)  }, [])
  const closeControls = useCallback(() => { blurRef.current = setTimeout(() => setSearchFocused(false), 150) }, [])

  useEffect(() => () => {
    clearTimeout(timerRef.current as ReturnType<typeof setTimeout>)
    clearTimeout(blurRef.current  as ReturnType<typeof setTimeout>)
  }, [])

  // keyboard shortcuts
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key === 'Escape') {
        searchRef.current?.blur()
        setExpanded(false)
        setSearchFocused(false)
      }
    }
    document.addEventListener('keydown', fn)
    return () => document.removeEventListener('keydown', fn)
  }, [])

  const showControls = searchFocused || hasActive

  return (
    <div className="fb-root">
      {/* Search — always visible */}
      <div className="fb-search-row">
        <div className="fb-search-wrap">
          <span className="fb-search-icon">⌕</span>
          <input
            ref={searchRef}
            className="fb-search"
            type="search"
            placeholder="Search events, artists, venues…"
            defaultValue={filters.search}
            onChange={e => handleSearch(e.target.value)}
            onFocus={openControls}
            onBlur={closeControls}
          />
          {filters.search && (
            <button className="fb-search-clear" onClick={() => {
              onPatch({ search: '' })
              if (searchRef.current) searchRef.current.value = ''
            }}>✕</button>
          )}
        </div>
      </div>

      {/* Filter controls — slide down on search focus or active filter */}
      <div className={`fb-controls ${showControls ? 'open' : ''}`} onMouseDown={openControls}>

        {/* Category pills + filter toggle */}
        <div className="fb-cats">
          {CATS.map(c => (
            <button
              key={c.id}
              className={`fb-cat-pill ${filters.category === c.id ? 'active' : ''}`}
              onClick={() => onPatch({ category: c.id })}
            >
              {c.label}
            </button>
          ))}
          <button
            className={`fb-cat-pill fb-filter-pill ${expanded ? 'active' : ''} ${hasActive && !expanded ? 'has-active' : ''}`}
            onClick={() => setExpanded(x => !x)}
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
                    onClick={() => onPatch({ date: d.id })}
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
                  onChange={e => onPatch({ neighborhood: e.target.value })}
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
                  onChange={e => onPatch({ free: e.target.checked })}
                />
                <span className="fb-toggle-track">
                  <span className="fb-toggle-thumb" />
                </span>
                Free only
              </label>
              {hasActive && (
                <button className="fb-clear" onClick={() => { onClear(); setExpanded(false) }}>
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
    </div>
  )
}
