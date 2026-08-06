import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { bootstrapAuth } from './auth/authStore'
import { bindBrandsToAuth } from './brands/brandsStore'
import './index.css'
import App from './App.tsx'

bindBrandsToAuth()
bootstrapAuth()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
