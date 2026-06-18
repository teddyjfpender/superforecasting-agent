import { Box, Text, useInput } from '@hermes/ink'
import { useEffect, useRef, useState } from 'react'

import { qrLines } from '../lib/qrRender.js'
import {
  type BinaryStatus,
  findJava,
  findSignalCli,
  parseMajorVersion,
  startDaemon
} from '../lib/signalDaemon.js'
import {
  brewInstall,
  CAPTCHA_URL,
  type InstallHandle,
  type LinkHandle,
  listAccounts,
  registerNumber,
  runLink,
  verifyNumber
} from '../lib/signalOnboard.js'
import type { Theme } from '../theme.js'

// In-TUI Signal onboarding wizard, painted over the Messaging view (press `s`).
// Detects/installs signal-cli, then either links this device to an existing
// account (renders the scan QR) or registers a new number (captcha + code), and
// finally starts the daemon on a free port — no leaving the TUI, no manual port.

type Step =
  | 'install'
  | 'linking'
  | 'menu'
  | 'reg-captcha'
  | 'reg-code'
  | 'reg-number'
  | 'starting'

interface SignalSetupModalProps {
  cols: number
  onCancel: () => void
  onConnected: () => void
  rows: number
  t: Theme
}

const tail = (lines: string[], n: number) => lines.slice(-n)

export function SignalSetupModal({ cols, onCancel, onConnected, rows, t }: SignalSetupModalProps) {
  const [step, setStep] = useState<Step>('menu')
  const [cli, setCli] = useState<BinaryStatus>({ found: false, path: '', version: '' })
  const [java, setJava] = useState<BinaryStatus>({ found: false, path: '', version: '' })
  const [input, setInput] = useState('')
  const [number, setNumber] = useState('')
  const [log, setLog] = useState<string[]>([])
  const [error, setError] = useState('')
  const [linkUri, setLinkUri] = useState('')
  const [busy, setBusy] = useState(false)

  const handleRef = useRef<InstallHandle | LinkHandle | null>(null)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    setCli(findSignalCli())
    setJava(findJava())

    return () => {
      aliveRef.current = false
      handleRef.current?.cancel()
    }
  }, [])

  const modalW = Math.max(54, Math.min(cols - 4, 100))
  const modalH = Math.max(16, Math.min(rows - 4, 36))

  const javaOk = java.found && parseMajorVersion(java.version) >= 17
  const ready = cli.found && javaOk

  const appendLog = (line: string) => {
    if (line && aliveRef.current) {
      setLog(prev => [...prev, line])
    }
  }

  const begin = (account: string) => {
    setStep('starting')
    setBusy(true)
    setError('')

    void (async () => {
      const { error: err } = await startDaemon(account)

      if (!aliveRef.current) {
        return
      }

      setBusy(false)

      if (err) {
        setError(err)
        setStep('menu')

        return
      }

      onConnected()
    })()
  }

  const install = (pkg: string) => {
    setStep('install')
    setLog([])
    setError('')

    const handle = brewInstall(pkg, {
      onDone: ok => {
        if (!aliveRef.current) {
          return
        }

        setCli(findSignalCli())
        setJava(findJava())

        if (!ok) {
          setError(`Couldn't install ${pkg} via Homebrew. See the manual steps below.`)
        }

        setStep('menu')
      },
      onLog: appendLog
    })

    if (!handle) {
      setError('Homebrew not found — install signal-cli (and Java 17+) manually, then press r.')
      setStep('menu')

      return
    }

    handleRef.current = handle
  }

  const startLink = () => {
    const name = input.trim() || 'Outrider'
    setInput('')
    setLinkUri('')
    setLog([])
    setError('')
    setStep('linking')
    handleRef.current = runLink(name, {
      onDone: (ok, err) => {
        if (!aliveRef.current) {
          return
        }

        if (!ok) {
          setError(err || 'linking failed')
          setStep('menu')

          return
        }
        // Linking doesn't tell us our own number — discover it.
        void (async () => {
          const accounts = await listAccounts()

          if (!aliveRef.current) {
            return
          }

          const acct = accounts[accounts.length - 1] || number

          if (!acct) {
            setError('Linked, but could not determine the account number.')
            setStep('menu')

            return
          }

          begin(acct)
        })()
      },
      onLog: appendLog,
      onUri: uri => aliveRef.current && setLinkUri(uri)
    })
  }

  const doRegister = (captcha?: string) => {
    setBusy(true)
    setError('')

    void (async () => {
      const r = await registerNumber(number, captcha ? { captcha } : {})

      if (!aliveRef.current) {
        return
      }

      setBusy(false)
      setInput('')

      if (r.ok) {
        setStep('reg-code')
      } else if (r.needsCaptcha) {
        setStep('reg-captcha')
      } else {
        setError(r.error || 'registration failed')
      }
    })()
  }

  const doVerify = () => {
    const code = input.trim()
    setBusy(true)
    setError('')

    void (async () => {
      const r = await verifyNumber(number, code)

      if (!aliveRef.current) {
        return
      }

      setBusy(false)
      setInput('')

      if (!r.ok) {
        setError(r.error || 'verification failed')

        return
      }

      begin(number)
    })()
  }

  useInput((ch, key) => {
    if (busy) {
      if (key.escape) {
        onCancel()
      }

      return
    }

    // Text-entry steps capture typing.
    const isTextStep = step === 'reg-number' || step === 'reg-captcha' || step === 'reg-code' || step === 'linking'
    const isNameStep = step === 'menu' // name is entered inline on the link menu? no — handled below

    if (key.escape) {
      if (step === 'menu') {
        return onCancel()
      }

      handleRef.current?.cancel()
      setStep('menu')
      setInput('')
      setError('')

      return
    }

    if (step === 'menu') {
      if (ch === 'l' && ready) {
        // Jump straight to link with a default name (most users keep it).
        setInput('')

        return startLink()
      }

      if (ch === 'n' && ready) {
        setInput('')

        return setStep('reg-number')
      }

      if (ch === 'i' && !cli.found) {
        return install('signal-cli')
      }

      if (ch === 'j' && !javaOk) {
        return install('openjdk')
      }

      if (ch === 'r') {
        setCli(findSignalCli())
        setJava(findJava())
      }

      return
    }

    if (isNameStep) {
      return
    }

    if (isTextStep && step !== 'linking') {
      if (key.return) {
        if (step === 'reg-number') {
          setNumber(input.trim())

          return doRegister()
        }

        if (step === 'reg-captcha') {
          return doRegister(input.trim())
        }

        if (step === 'reg-code') {
          return doVerify()
        }
      }

      if (key.backspace || key.delete) {
        return setInput(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setInput(s => s + printable)
        }
      }
    }
  })

  // ---- rendering -----------------------------------------------------------
  const prereqLine = (label: string, ok: boolean, detail: string) => (
    <Text wrap="truncate-end">
      <Text color={ok ? t.color.ok : t.color.error}>{ok ? '✓' : '✗'} </Text>
      <Text color={t.color.label}>{label.padEnd(11)}</Text>
      <Text color={t.color.muted}>{detail}</Text>
    </Text>
  )

  const field = (label: string, placeholder: string) => (
    <Box flexDirection="column" marginTop={1}>
      <Text color={t.color.label}>{label}</Text>
      <Box marginTop={1}>
        <Text color={t.color.muted}>{'› '}</Text>
        <Text color={t.color.text}>{input || ''}</Text>
        <Text color={t.color.text} inverse>
          {' '}
        </Text>
        {!input ? <Text color={t.color.muted}> {placeholder}</Text> : null}
      </Box>
    </Box>
  )

  let body: React.ReactNode
  let footer = 'Esc cancel'

  if (step === 'install') {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.accent}>Installing via Homebrew…</Text>
        <Box flexDirection="column" marginTop={1}>
          {tail(log, modalH - 8).map((l, i) => (
            <Text color={t.color.muted} key={i} wrap="truncate-end">
              {l}
            </Text>
          ))}
        </Box>
      </Box>
    )
    footer = 'Esc cancel'
  } else if (step === 'linking') {
    body = (
      <Box flexDirection="column">
        {linkUri ? (
          <Box alignItems="center" flexDirection="column">
            <Text color={t.color.label} wrap="truncate-end">
              Open Signal on your phone → Settings → Linked devices → + → scan:
            </Text>
            {/* Centered, on-theme (cream field + near-black modules) but still
                high-contrast so the scanner reads it cleanly. */}
            <Box flexDirection="column" marginTop={1}>
              {qrLines(linkUri).map((line, i) => (
                <Text backgroundColor={t.color.text} color={t.color.statusBg} key={i}>
                  {line}
                </Text>
              ))}
            </Box>
            <Box marginTop={1}>
              <Text color={t.color.muted}>Waiting for your phone to confirm…</Text>
            </Box>
          </Box>
        ) : (
          <Text color={t.color.muted}>Generating a device-link code…</Text>
        )}
      </Box>
    )
    footer = 'Esc cancel'
  } else if (step === 'reg-number') {
    body = field('Register a new Signal number (E.164, e.g. +15551234567):', '+15551234567')
    footer = '⏎ request code · Esc back'
  } else if (step === 'reg-captcha') {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.label} wrap="wrap">
          Signal needs a captcha. Open this in a browser, solve it, then copy the resulting
          {' '}signalcaptcha:// link:
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.accent} wrap="truncate-end">
            {CAPTCHA_URL}
          </Text>
        </Box>
        {field('Paste the signalcaptcha:// token:', 'signalcaptcha://…')}
      </Box>
    )
    footer = '⏎ submit captcha · Esc back'
  } else if (step === 'reg-code') {
    body = field(`Enter the code Signal sent to ${number}:`, '123-456')
    footer = '⏎ verify · Esc back'
  } else if (step === 'starting') {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.accent}>Starting the Signal daemon on a free port…</Text>
        <Text color={t.color.muted} wrap="wrap">
          Loading your account and connecting. This can take a few seconds.
        </Text>
      </Box>
    )
    footer = 'Esc cancel'
  } else {
    // menu
    body = (
      <Box flexDirection="column">
        <Text color={t.color.label}>Prerequisites</Text>
        <Box flexDirection="column" marginTop={1}>
          {prereqLine('signal-cli', cli.found, cli.found ? cli.version : 'not found')}
          {prereqLine('Java 17+', javaOk, java.found ? java.version : 'not found')}
        </Box>
        <Box flexDirection="column" marginTop={1}>
          {!cli.found ? <Text color={t.color.warn}>[i] install signal-cli (Homebrew)</Text> : null}
          {cli.found && !javaOk ? <Text color={t.color.warn}>[j] install Java 17+ (Homebrew)</Text> : null}
          <Text color={ready ? t.color.text : t.color.muted}>[l] Link an existing Signal account (scan a QR)</Text>
          <Text color={ready ? t.color.text : t.color.muted}>[n] Register a new phone number</Text>
        </Box>
        {!ready ? (
          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="wrap">
              Install the prerequisites above first. [r] re-check after installing.
            </Text>
          </Box>
        ) : null}
      </Box>
    )
    footer = ready ? 'l link · n register · r recheck · Esc close' : 'i/j install · r recheck · Esc close'
  }

  return (
    <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
      <Box
        borderColor={t.color.accent}
        borderStyle="round"
        flexDirection="column"
        height={modalH}
        paddingX={2}
        paddingY={1}
        width={modalW}
      >
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary}>
            Connect Signal
          </Text>
          <Text color={t.color.muted}>setup</Text>
        </Box>
        <Box flexDirection="column" flexGrow={1} marginTop={1} minHeight={0} overflow="hidden">
          {body}
          {error ? (
            <Box marginTop={1}>
              <Text color={t.color.error} wrap="wrap">
                {error}
              </Text>
            </Box>
          ) : null}
        </Box>
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            {footer}
          </Text>
        </Box>
      </Box>
    </Box>
  )
}
