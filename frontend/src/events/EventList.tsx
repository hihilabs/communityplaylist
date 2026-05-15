import { useMemo } from 'react'
import { EventCard } from './EventCard'
import type { Event } from './types'

interface Props {
  events: Event[]
  loading: boolean
  error: boolean
  onCategoryClick: (cat: string) => void
  onNeighborhoodClick: (hood: string) => void
}

export function EventList({ events, loading, error, onCategoryClick, onNeighborhoodClick }: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, Event[]>()
    for (const ev of events) {
      const key = ev.day_label
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(ev)
    }
    return Array.from(map.entries())
  }, [events])

  if (loading) return (
    <div className="ev-state">
      <div className="ev-spinner" />
      <p>Loading events…</p>
    </div>
  )

  if (error) return (
    <div className="ev-state ev-error">
      <p>Could not load events. Try refreshing.</p>
    </div>
  )

  if (events.length === 0) return (
    <div className="ev-state ev-empty">
      <p>No events match your filters.</p>
    </div>
  )

  return (
    <div className="ev-list">
      {groups.map(([day, evs]) => (
        <section key={day} className="ev-day-group">
          <div className="ev-day-label">
            <span>{day}</span>
            <span className="ev-day-count">{evs.length}</span>
          </div>
          <div className="ev-cards">
            {evs.map(ev => (
              <EventCard
                key={ev.id}
                event={ev}
                onCategoryClick={onCategoryClick}
                onNeighborhoodClick={onNeighborhoodClick}
              />
            ))}
          </div>
        </section>
      ))}
      <div className="ev-footer">
        <a href="/events/archive/" className="ev-archive-link">View past events →</a>
      </div>
    </div>
  )
}
