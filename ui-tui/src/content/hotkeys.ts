import { isMac, isRemoteShell } from '../lib/platform.js'

const action = isMac ? 'Cmd' : 'Ctrl'
const paste = isMac ? 'Cmd' : 'Alt'

const copyHotkeys: [string, string][] = isMac
  ? [
      ['Cmd+C', 'copy selection'],
      ['Ctrl+C', 'interrupt / clear draft / exit']
    ]
  : isRemoteShell()
    ? [
        ['Cmd+C', 'copy selection when forwarded by the terminal'],
        ['Ctrl+C', 'copy selection / interrupt / clear draft / exit']
      ]
    : [['Ctrl+C', 'copy selection / interrupt / clear draft / exit']]

export const HOTKEYS: [string, string][] = [
  ...copyHotkeys,
  // Mouse tracking is on (click zones, wheel, scrollbar drag), so a plain drag
  // runs the IN-APP selection. While the chat is streaming that highlight can
  // jitter as new lines land under the cursor — hold Shift to fall back to the
  // terminal's own native selection, which the app never touches (rock steady).
  ['drag · Shift+drag', 'select text — plain drag = in-app select; hold Shift for the terminal’s native selection (steady while streaming)'],
  [action + '+D', 'exit'],
  [action + '+G / Alt+G', 'open $EDITOR (Alt+G fallback for VSCode/Cursor)'],
  [action + '+L', 'redraw / repaint'],
  [paste + '+V / /paste', 'paste text; /paste attaches clipboard image'],
  ['Ctrl+F', 'start forecast search; converts a typed phrase into /find <phrase>'],
  ['Alt/Option+1..9 or /1..9', 'forecast views: book, review, alerts, evidence, learning, schedules, calibration, backtests, all'],
  ['/calibration --visual', 'full-screen calibration view: reliability curve, buckets, signed bias verdict'],
  ['Tab', 'apply completion'],
  ['↑/↓', 'completions / queue edit / history'],
  ['Ctrl+X', 'delete the queued forecast note you’re editing (Esc cancels edit)'],
  [action + '+A/E', 'home / end of line'],
  [action + '+Z / ' + action + '+Y', 'undo / redo input edits'],
  [action + '+W', 'delete word'],
  [action + '+U/K', 'delete to start / end'],
  [action + '+←/→', 'jump word'],
  ['Home/End', 'start / end of line'],
  ['Shift+Enter / Alt+Enter', 'insert newline'],
  ['\\+Enter', 'multi-line continuation (fallback)'],
  ['!<cmd>', 'run a shell command (e.g. !ls, !git status)'],
  ['{!<cmd>}', 'interpolate shell output inline (e.g. "branch is {!git branch --show-current}")']
]
