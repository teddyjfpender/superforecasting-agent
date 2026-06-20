import { atom } from 'nanostores'

// Which Home pane has keyboard focus. 'conversation' is the default: typing
// goes to the composer and ↑↓/PageUp scroll the conversation. 'rail' hands the
// keyboard to the conversations rail (↑↓ to move the selection, Enter to open)
// and deactivates the composer's input. Only meaningful in the wide two-pane
// Home; reset to 'conversation' whenever the rail isn't shown.
export type HomePane = 'conversation' | 'rail'

export interface HomeFocusState {
  pane: HomePane
}

export const $homeFocus = atom<HomeFocusState>({ pane: 'conversation' })

export const getHomeFocus = () => $homeFocus.get()

export const setHomePane = (pane: HomePane) => {
  if ($homeFocus.get().pane !== pane) {
    $homeFocus.set({ pane })
  }
}
