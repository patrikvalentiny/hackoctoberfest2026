import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['offshore.svg'],
      manifest: {
        name: 'Harbour Pulse',
        short_name: 'Harbour Pulse',
        description: 'Work-window planning for offshore wind technicians.',
        theme_color: '#0e5a6b',
        background_color: '#eef2f1',
        display: 'standalone',
        orientation: 'any',
        icons: [
          {
            src: '/offshore.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,woff2,webmanifest}'],
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        // Keep the Google Fonts files so the app looks the same offline.
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\/.*/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts',
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(fileURLToPath(new URL('.', import.meta.url)), 'src'),
    },
  },
})
