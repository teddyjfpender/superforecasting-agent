import { useInput } from '@superforecasting/ink'

type Key = Parameters<Parameters<typeof useInput>[0]>[1]
type Handler = (input: string, key: Key) => unknown

/** Only unambiguous action chips dispatch; combined navigation legends remain hints. */
export const footerKey = (label: string): { input: string; key: Key } | null => {
  const names: Record<string, keyof Key> = {
    Enter: 'return',
    '⏎': 'return',
    Esc: 'escape',
    '⎋': 'escape',
    Tab: 'tab',
    '⇥': 'tab'
  }

  const key: Key = {
    upArrow: false,
    downArrow: false,
    leftArrow: false,
    rightArrow: false,
    pageDown: false,
    pageUp: false,
    wheelUp: false,
    wheelDown: false,
    home: false,
    end: false,
    return: false,
    escape: false,
    ctrl: false,
    shift: false,
    fn: false,
    tab: false,
    backspace: false,
    delete: false,
    meta: false,
    alt: false,
    super: false
  }

  const named = names[label]

  if (named) {
    Object.assign(key, { [named]: true })

    return { input: '', key }
  }

  if (label === 'Space') {
    return { input: ' ', key }
  }

  if (/^\^[A-Za-z]$/.test(label)) {
    return { input: label[1]!.toLowerCase(), key: { ...key, ctrl: true } }
  }

  if (label.length !== 1 || !/^[ -~]$/.test(label)) {
    return null
  }

  return { input: label, key: { ...key, shift: /^[A-Z]$/.test(label) } }
}

/** Keyboard and footer clicks share the view's existing mode guards and actions. */
export function useViewInput(handler: Handler, options: { isActive?: boolean } = {}) {
  useInput(handler, options)

  return (label: string) => {
    const event = footerKey(label)

    if (event && options.isActive !== false) {
      handler(event.input, event.key)
    }
  }
}
