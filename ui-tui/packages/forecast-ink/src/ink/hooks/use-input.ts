import { useLayoutEffect, useRef } from 'react'

import type { InputEvent, Key } from '../events/input-event.js'

import useStdin from './use-stdin.js'

type Handler = (input: string, key: Key, event: InputEvent) => void

type Options = {
  /**
   * Enable or disable capturing of user input.
   * Useful when there are multiple useInput hooks used at once to avoid handling the same input several times.
   *
   * @default true
   */
  isActive?: boolean
}

/**
 * This hook is used for handling user input.
 * It's a more convenient alternative to using `StdinContext` and listening to `data` events.
 * The callback you pass to `useInput` is called for each character when user enters any input.
 * However, if user pastes text and it's more than one character, the callback will be called only once and the whole string will be passed as `input`.
 *
 * ```
 * import {useInput} from 'ink';
 *
 * const UserInput = () => {
 *   useInput((input, key) => {
 *     if (input === 'q') {
 *       // Exit program
 *     }
 *
 *     if (key.leftArrow) {
 *       // Left arrow key pressed
 *     }
 *   });
 *
 *   return …
 * };
 * ```
 */
const useInput = (inputHandler: Handler, options: Options = {}) => {
  const { setRawMode, exitOnCtrlC, inputEmitter } = useStdin()

  // useLayoutEffect (not useEffect) so that raw mode is enabled synchronously
  // during React's commit phase, before render() returns. With useEffect, raw
  // mode setup is deferred to the next event loop tick via React's scheduler,
  // leaving the terminal in cooked mode — keystrokes echo and the cursor is
  // visible until the effect fires.
  useLayoutEffect(() => {
    if (options.isActive === false) {
      return
    }

    setRawMode(true)

    return () => {
      setRawMode(false)
    }
  }, [options.isActive, setRawMode])

  // Node must use a real layout effect: browser-detecting "isomorphic" helpers
  // choose passive effects in a terminal, leaving a painted control with a stale
  // handler (or no listener yet). Keep one listener slot and commit its handler
  // before users can act on the new frame, preserving propagation order.
  const current = useRef({ inputHandler, isActive: options.isActive, exitOnCtrlC })
  useLayoutEffect(() => {
    current.current = { inputHandler, isActive: options.isActive, exitOnCtrlC }
  })

  useLayoutEffect(() => {
    const handleData = (event: InputEvent) => {
      const state = current.current

      if (state.isActive === false) {
        return
      }

      const { input, key } = event

      // The App already emits within a discrete update.
      if (!(input === 'c' && key.ctrl) || !state.exitOnCtrlC) {
        state.inputHandler(input, key, event)
      }
    }

    inputEmitter?.on('input', handleData)

    return () => {
      inputEmitter?.removeListener('input', handleData)
    }
  }, [inputEmitter])
}

export default useInput
