import type { Event } from './types'

const CAT_LABEL: Record<string, string> = {
  music: '🎵 Music', arts: '🎨 Arts', bike: '🚲 Bike',
  fund: '💙 Fundraiser', food: '🍴 Food', hybrid: '⚡ Hybrid',
}

const CAT_EMOJI: Record<string, string> = {
  music: '🎵', arts: '🎨', bike: '🚲',
  fund: '💙', food: '🍴', hybrid: '⚡',
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
    <a
      className={`ev-card event ev-cat-${cat}${ev.is_happening_now ? ' ev-now' : ''}`}
      href={href}
      data-cat={cat}
      data-slug={ev.slug}
      data-lat={ev.latitude ?? undefined}
      data-lng={ev.longitude ?? undefined}
    >
      <div className="ev-card-body">
        <div className="ev-hdr">
          {cat && (
            <span
              className={`cat-badge cat-${cat}`}
              onClick={e => { e.preventDefault(); onCategoryClick(cat) }}
            >
              {CAT_LABEL[cat] ?? cat}
            </span>
          )}
          <span className="ev-time">
            {ev.is_happening_now
              ? <><span className="ev-now-dot"></span>NOW</>
              : <>{ev.day_label} · {ev.time_label}</>
            }
          </span>
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
      </div>

      <div className="ev-flyer-thumb">
        {ev.flyer_url
          ? <img src={ev.flyer_url} alt="" loading="lazy" />
          : <div className="ev-flyer-ph">{CAT_EMOJI[cat] ?? '🎵'}</div>
        }
      </div>
    </a>
  )
}
