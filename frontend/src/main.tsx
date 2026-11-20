import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './os/App';
import { registerPrograms } from './programs';

registerPrograms();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
