import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { aliasInviteLink } from './codes'

// an older ?room= or ?party= invite reads as ?code= before anything looks at the address
aliasInviteLink()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
