import { atom } from 'nanostores'

// True while the Warnings view OWNS a live automode pass (R free / Shift-A agent).
//
// The pass runs on the detached-jobs runtime in the gateway process, and a failing
// free tier logs LOUDLY — one line per alert (a 130/130 LedgerNotFound storm =
// 130 stderr rows). Those lines are ALWAYS captured in the gateway-client log
// buffer (visible via /logs), so nothing is lost; but while a pass owns the view
// the `gateway.stderr` -> transcript channel reads THIS flag to SUPPRESS them from
// the activity feed. Otherwise each line forces a render + grows the transcript,
// and the whole view scrolls up and down under a failing pass (the operator's
// report). The run's progress renders as a fixed inline bar in the Warnings chrome
// instead, so the transcript never moves while a pass is live.
export const $warningsRunActive = atom<boolean>(false)

// Set only when the value actually changed, so repeated true/false writes over a
// pass's lifecycle never churn subscribers.
export const setWarningsRunActive = (active: boolean): void => {
  if ($warningsRunActive.get() !== active) {
    $warningsRunActive.set(active)
  }
}

// Read side for the (non-React) gateway event handler.
export const isWarningsRunActive = (): boolean => $warningsRunActive.get()
