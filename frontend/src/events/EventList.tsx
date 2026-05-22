import { useMemo } from 'react'
import { EventCard } from './EventCard'
import type { Event, CommunityItem } from './types'

const COMM_EVERY = 9

interface Props {
  events: Event[]
  loading: boolean
  error: boolean
  onCategoryClick: (cat: string) => void
  onNeighborhoodClick: (hood: string) => void
  community: CommunityItem[]
}

function CommunityCard({ item }: { item: CommunityItem }) {
  const isRecord = item.type === 'record'
  return (
    <a href={item.url} className={`ev-card ${isRecord ? 'ev-cat-record' : 'ev-cat-community'}`}>
      <div className="ev-hdr">
        <span className={`cat-badge ${isRecord ? 'cat-record' : 'cat-community'}`}>
          {isRecord ? '🛒 Record Shop' : '🌹 Aid'}
        </span>
        {isRecord && item.price && <span className="ev-time">{item.price}</span>}
      </div>
      <h2>{isRecord ? `${item.artist} — ${item.title}` : item.text}</h2>
    </a>
  )
}

export function EventList({ events, loading, error, onCategoryClick, onNeighborhoodClick, community }: Props) {
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

  let globalIdx = 0

  return (
    <div className="ev-list">
      {groups.map(([day, evs]) => {
        const cards = evs.flatMap(ev => {
          globalIdx++
          const nodes = [
            <EventCard
              key={ev.id}
              event={ev}
              onCategoryClick={onCategoryClick}
              onNeighborhoodClick={onNeighborhoodClick}
            />
          ]
          if (globalIdx % COMM_EVERY === 0 && community.length > 0) {
            const item = community[Math.floor(globalIdx / COMM_EVERY - 1) % community.length]
            nodes.push(<CommunityCard key={`comm-${globalIdx}`} item={item} />)
          }
          return nodes
        })

        return (
          <section key={day} className="ev-day-group">
            <div className="ev-day-label">
              <span>{day}</span>
              <span className="ev-day-count">{evs.length}</span>
            </div>
            <div className="ev-cards">{cards}</div>
          </section>
        )
      })}
      <div className="ev-footer">
        <a href="/events/archive/" className="ev-archive-link">View past events →</a>
      </div>
    </div>
  )
}
