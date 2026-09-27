import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';
import { registerSW } from 'virtual:pwa-register';
import { Providers } from './providers.tsx';
import { router } from './router.tsx';
import '../styles/index.css';

registerSW({ immediate: true });

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');

createRoot(root).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
