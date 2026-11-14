import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { aliasPartyLink } from './codes'

// an older ?party= invite reads as ?code= before anything looks at the address
aliasPartyLink()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
