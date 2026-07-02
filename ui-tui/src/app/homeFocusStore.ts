import { atom } from 'nanostores'

// Which Home pane has keyboard focus. 'conversation' is the default: typing
// goes to the composer and ↑↓/PageUp scroll the conversation. 'rail' hands the
// keyboard to the conversations rail (↑↓ to move the selection, Enter to open)
// and deactivates the composer's input. 'today' hands the keyboard to the
// landing "Today" attention panel (↑↓ select, ⏎ open, a alerts, n new) and
// likewise deactivates the composer. Only the wide two-pane Home shows the rail;
// 'today' is meaningful only on the landing where the Today panel is mounted.
// Reset to 'conversation' whenever the owning pane isn't shown.
export type HomePane = 'conversation' | 'rail' | 'today'

export interface HomeFocusState {
  pane: HomePane
  // How many actionable rows the Today panel is currently showing. The global
  // key handler reads this to decide whether the `t` leader should grab focus
  // (0 → the panel is empty/absent, so `t` types normally). The Today panel is
  // the sole writer (setTodayCount), and it drops back to 0 on unmount.
  todayCount: number
}

export const $homeFocus = atom<HomeFocusState>({ pane: 'conversation', todayCount: 0 })

export const getHomeFocus = () => $homeFocus.get()

export const setHomePane = (pane: HomePane) => {
  const state = $homeFocus.get()

  if (state.pane !== pane) {
    $homeFocus.set({ ...state, pane })
  }
}

// The Today panel reports how many actionable rows it holds. When it empties
// (0) while it still holds focus, hand the keyboard back to the composer so the
// user is never trapped in an empty panel.
export const setTodayCount = (count: number) => {
  const state = $homeFocus.get()
  const next = Math.max(0, Math.floor(count) || 0)

  if (state.todayCount === next) {
    return
  }

  const pane: HomePane = next === 0 && state.pane === 'today' ? 'conversation' : state.pane
  $homeFocus.set({ pane, todayCount: next })
}
