// first: the app's one-time handoff is written before any module reads storage
import './originMove'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { aliasInviteLink } from './codes'
import { NearbyDebugMount } from './nearbyGate'
import { loadLanguage } from './i18n'

// an older ?room= or ?party= invite reads as ?code= before anything looks at the address
aliasInviteLink()

function render() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
      <NearbyDebugMount />
    </StrictMode>,
  )
}

// in the app, the language chosen on either launch path (hosted or the
// bundled offline page) is read from the native store before anything draws
const language = loadLanguage()
if (language) void language.finally(render)
else render()
