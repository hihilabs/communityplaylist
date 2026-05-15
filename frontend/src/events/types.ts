export interface Event {
  id: number
  title: string
  slug: string
  start_date: string       // ISO string
  end_date: string | null
  location: string
  neighborhood: string | null
  hood_slug: string | null
  category: string
  is_free: boolean
  price_info: string
  genres: string[]
  artists: string[]
  flyer_url: string
  website: string
  latitude: number | null
  longitude: number | null
  is_happening_now: boolean
  is_today: boolean
  day_label: string        // "Today", "Tomorrow", "Fri May 16"
  time_label: string       // "9 PM"
  venue_name: string
}

export interface FilterState {
  search: string
  category: string
  date: string             // 'today' | 'tomorrow' | 'weekend' | ''
  neighborhood: string
  free: boolean
}

export type ViewMode = 'list' | 'map' | 'hybrid'
