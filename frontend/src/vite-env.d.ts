/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend API in a deployed build (e.g. https://app.onrender.com). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
