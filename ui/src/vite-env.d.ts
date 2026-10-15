/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "0" sends /api to the backend; anything else uses the mocks (development only) */
  readonly VITE_MOCK?: string
  /** the backend the dev server proxies to when VITE_MOCK=0 */
  readonly VITE_BACKEND?: string
}
