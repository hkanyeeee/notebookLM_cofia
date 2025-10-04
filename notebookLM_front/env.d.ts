/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// Type shim for marked-katex-extension (no official types)
declare module 'marked-katex-extension' {
  import type { MarkedExtension } from 'marked'
  export function markedKatex(options?: any): MarkedExtension
}
