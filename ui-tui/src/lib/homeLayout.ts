// Geometry for the Home two-pane layout (conversations rail + conversation),
// shared so the renderer (appLayout.tsx) and the wheel router (useInputHandlers)
// agree on where the rail ends. The rail occupies the leftmost RAIL_WIDTH
// columns; everything to its right is the conversation pane.

export const RAIL_WIDTH = 30

// Only split into two panes on terminals wide enough that the conversation
// still gets a comfortable column after the rail is carved off.
export const RAIL_MIN_COLS = 84

export const showRailFor = (cols: number): boolean => cols >= RAIL_MIN_COLS
