import { useState, useEffect, useMemo, useCallback } from 'react'
import type { Event, FilterState } from './types'

interface ApiResponse {
  events: Event[]
  neighborhoods: string[]
  genres: string[]
}

export function useEvents(apiUrl: string) {
  const [all, setAll] = useState<Event[]>([])
  const [neighborhoods, setNeighborhoods] = useState<string[]>([])
  const [genres, setGenres] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [filters, setFilters] = useState<FilterState>({
    search: '',
    category: '',
    date: '',
    neighborhood: '',
    free: false,
  })

  useEffect(() => {
    fetch(apiUrl)
      .then(r => r.json())
      .then((data: ApiResponse) => {
        setAll(data.events)
        setNeighborhoods(data.neighborhoods)
        setGenres(data.genres)
        setLoading(false)
      })
      .catch(() => { setError(true); setLoading(false) })
  }, [apiUrl])

  const filtered = useMemo(() => {
    const q = filters.search.toLowerCase()
    return all.filter(ev => {
      if (q && !ev.title.toLowerCase().includes(q) &&
          !ev.location.toLowerCase().includes(q) &&
          !ev.artists.some(a => a.toLowerCase().includes(q)) &&
          !ev.genres.some(g => g.toLowerCase().includes(q))) return false
      if (filters.category && ev.category !== filters.category) return false
      if (filters.free && !ev.is_free) return false
      if (filters.neighborhood && ev.neighborhood !== filters.neighborhood) return false
      if (filters.date) {
        const d = new Date(ev.start_date)
        const today = new Date(); today.setHours(0,0,0,0)
        const tomorrow = new Date(today); tomorrow.setDate(tomorrow.getDate() + 1)
        const dayAfter = new Date(tomorrow); dayAfter.setDate(dayAfter.getDate() + 1)
        const sat = new Date(today)
        sat.setDate(today.getDate() + (6 - today.getDay()))
        const mon = new Date(sat); mon.setDate(sat.getDate() + 2)
        if (filters.date === 'today' && (d < today || d >= tomorrow)) return false
        if (filters.date === 'tomorrow' && (d < tomorrow || d >= dayAfter)) return false
        if (filters.date === 'weekend' && (d < sat || d >= mon)) return false
      }
      return true
    })
  }, [all, filters])

  const patch = useCallback((partial: Partial<FilterState>) =>
    setFilters(f => ({ ...f, ...partial })), [])

  const clear = useCallback(() =>
    setFilters({ search: '', category: '', date: '', neighborhood: '', free: false }), [])

  const hasActive = filters.search || filters.category || filters.date ||
                    filters.neighborhood || filters.free

  return { filtered, all, neighborhoods, genres, loading, error, filters, patch, clear, hasActive }
}
