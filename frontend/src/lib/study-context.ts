import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

/**
 * Global study/site context store.
 * Users select a study and site to scope their view of clinical data.
 * Frontend convenience only — server enforces authorization.
 */
interface StudyContextState {
  selectedStudyId: string | null
  selectedStudyName: string | null
  selectedSiteId: string | null
  selectedSiteName: string | null
  setStudy: (studyId: string | null, studyName?: string | null) => void
  setSite: (siteId: string | null, siteName?: string | null) => void
  clear: () => void
}

export const useStudyContext = create<StudyContextState>()(persist(
  (set) => ({
    selectedStudyId: null,
    selectedStudyName: null,
    selectedSiteId: null,
    selectedSiteName: null,

    setStudy: (studyId, studyName) => set((state) => {
      const sameStudy = studyId === state.selectedStudyId
      return {
        selectedStudyId: studyId,
        selectedStudyName: studyName ?? (sameStudy ? state.selectedStudyName : null),
        selectedSiteId: sameStudy ? state.selectedSiteId : null,
        selectedSiteName: sameStudy ? state.selectedSiteName : null,
      }
    }),
    setSite: (siteId, siteName) => set((state) => ({
      selectedSiteId: siteId,
      selectedSiteName: siteName ?? (siteId === state.selectedSiteId ? state.selectedSiteName : null),
    })),
    clear: () => set({
      selectedStudyId: null,
      selectedStudyName: null,
      selectedSiteId: null,
      selectedSiteName: null,
    }),
  }),
  {
    name: 'edc-study-context',
    storage: createJSONStorage(() => localStorage),
    partialize: ({ selectedStudyId, selectedStudyName, selectedSiteId, selectedSiteName }) => ({
      selectedStudyId,
      selectedStudyName,
      selectedSiteId,
      selectedSiteName,
    }),
  },
))
