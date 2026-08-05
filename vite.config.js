import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  base: '/mon-projet-orage/', // <-- LA LIGNE MAGIQUE EST ICI (avec les slashs !)
  plugins: [react()],
})