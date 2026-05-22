import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { EventsApp } from './EventsApp'
import type { CommunityItem } from './types'
import './styles.css'

const el = document.getElementById('cp-events-root')
if (el) {
  const apiUrl = el.dataset.eventsUrl ?? '/api/events/'
  let community: CommunityItem[] = []
  try { community = JSON.parse(el.dataset.community || '[]') } catch {}
  createRoot(el).render(
    <StrictMode>
      <EventsApp apiUrl={apiUrl} community={community} />
    </StrictMode>
  )
}
