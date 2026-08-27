import { create } from 'zustand'

/**
 * Global study/site context store.
 * Users select a study and site to scope their view of clinical data.
 * Frontend convenience only — server enforces authorization.
 */
interface StudyContextState {
  selectedStudyId: string | null
  selectedSiteId: string | null
  setStudy: (studyId: string | null) => void
  setSite: (siteId: string | null) => void
  clear: () => void
}

export const useStudyContext = create<StudyContextState>((set) => ({
  selectedStudyId: null,
  selectedSiteId: null,

  setStudy: (studyId) => set({ selectedStudyId: studyId, selectedSiteId: null }),
  setSite: (siteId) => set({ selectedSiteId: siteId }),
  clear: () => set({ selectedStudyId: null, selectedSiteId: null }),
}))
