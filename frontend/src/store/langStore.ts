/** Language preference store — persisted to localStorage. */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { translations } from '../i18n'
import type { Lang } from '../i18n'

type AnyTranslation = typeof translations[Lang]

interface LangState {
  lang: Lang
  t: AnyTranslation
  setLang: (lang: Lang) => void
}

export const useLangStore = create<LangState>()(
  persist(
    (set) => ({
      lang: 'nl',
      t: translations.nl,
      setLang: (lang: Lang) => set({ lang, t: translations[lang] }),
    }),
    { name: 'geokaart-lang' }
  )
)
