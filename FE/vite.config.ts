import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const backendUrl = env.VITE_BACKEND_URL || 'http://127.0.0.1:8005';

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 3000,
      strictPort: true,
      proxy: {
        '/bounds': backendUrl,
        '/ndvi_data': backendUrl,
        '/roi_ndvi': backendUrl,
        '/roi_indices': backendUrl,
        '/recortar': backendUrl,
        '/crop_tiles': backendUrl,
        '/static': backendUrl,
        '/tree_points': backendUrl,
        '/ortho_analysis': backendUrl,
        '/orthomosaics': backendUrl,
        '/rois': backendUrl,
        '/vegetation_indices': backendUrl,
        '/tiles': backendUrl,
      },
    },
  };
});
