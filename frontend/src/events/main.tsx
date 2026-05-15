import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { EventsApp } from './EventsApp'
import './styles.css'

const el = document.getElementById('cp-events-root')
if (el) {
  const apiUrl = el.dataset.eventsUrl ?? '/api/events/'
  createRoot(el).render(
    <StrictMode>
      <EventsApp apiUrl={apiUrl} />
    </StrictMode>
  )
}
