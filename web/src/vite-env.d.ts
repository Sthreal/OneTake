/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MINICLAW_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
