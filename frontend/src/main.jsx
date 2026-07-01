import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { installApiRoleHeader } from './utils/apiRoleHeader.js'
import App from './App.jsx'

installApiRoleHeader()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
