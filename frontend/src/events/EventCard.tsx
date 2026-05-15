import type { Event } from './types'

const CAT_LABEL: Record<string, string> = {
  music: '🎵 Music', arts: '🎨 Arts', bike: '🚲 Bike',
  fund: '💙 Fundraiser', food: '🍴 Food', hybrid: '⚡ Hybrid',
}

interface Props {
  event: Event
  onCategoryClick: (cat: string) => void
  onNeighborhoodClick: (hood: string) => void
}

export function EventCard({ event: ev, onCategoryClick, onNeighborhoodClick }: Props) {
  const cat = ev.category || 'music'
  const href = `/events/${ev.slug}/`

  return (
    <a className={`ev-card ev-cat-${cat}`} href={href} data-cat={cat}>
      <div className="ev-hdr">
        {cat && (
          <span
            className={`cat-badge cat-${cat}`}
            onClick={e => { e.preventDefault(); onCategoryClick(cat) }}
          >
            {CAT_LABEL[cat] ?? cat}
          </span>
        )}
        <span className="ev-time">{ev.day_label} · {ev.time_label}</span>
      </div>

      <h2>{ev.title}</h2>

      <div className="ev-meta">
        {ev.neighborhood && (
          <span
            className="hood-tag"
            onClick={e => { e.preventDefault(); onNeighborhoodClick(ev.neighborhood!) }}
          >
            📍 {ev.neighborhood}
          </span>
        )}
        {ev.location && <span className="ev-loc">· {ev.location}</span>}
        {ev.is_free
          ? <span className="ev-free">FREE</span>
          : ev.price_info && <span className="ev-price">{ev.price_info}</span>
        }
        {ev.genres.slice(0, 2).map(g => (
          <span key={g} className="genre-tag">{g}</span>
        ))}
      </div>

      {ev.artists.length > 0 && (
        <div className="ev-artists">
          {ev.artists.slice(0, 4).join(' · ')}
          {ev.artists.length > 4 && <span className="ev-more"> +{ev.artists.length - 4}</span>}
        </div>
      )}
    </a>
  )
}
