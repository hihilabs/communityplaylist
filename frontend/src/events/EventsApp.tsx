import { useCallback, useEffect } from 'react'
import { FilterBar } from './FilterBar'
import { EventList } from './EventList'
import { useEvents } from './useEvents'

interface Props {
  apiUrl: string
}

export function EventsApp({ apiUrl }: Props) {
  const { filtered, all, neighborhoods, loading, error, filters, patch, clear, hasActive } = useEvents(apiUrl)

  // Notify vanilla Leaflet map when filtered events change
  useEffect(() => {
    if (loading) return
    const mapEvents = filtered
      .filter(ev => ev.latitude !== null && ev.longitude !== null)
      .map(ev => ({
        title: ev.title,
        slug: ev.slug,
        latitude: ev.latitude,
        longitude: ev.longitude,
        location: ev.location,
        category: ev.category,
        start_date: ev.time_label,
        flyer_url: ev.flyer_url,
      }))
    window.dispatchEvent(new CustomEvent('cp:events-filtered', { detail: { events: mapEvents } }))
  }, [filtered, loading])

  const handleCategoryClick = useCallback((cat: string) => {
    patch({ category: filters.category === cat ? '' : cat })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filters.category, patch])

  const handleNeighborhoodClick = useCallback((hood: string) => {
    patch({ neighborhood: filters.neighborhood === hood ? '' : hood })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filters.neighborhood, patch])

  return (
    <>
      <FilterBar
        filters={filters}
        neighborhoods={neighborhoods}
        count={filtered.length}
        total={all.length}
        hasActive={!!hasActive}
        onPatch={patch}
        onClear={clear}
      />
      <EventList
        events={filtered}
        loading={loading}
        error={error}
        onCategoryClick={handleCategoryClick}
        onNeighborhoodClick={handleNeighborhoodClick}
      />
    </>
  )
}
