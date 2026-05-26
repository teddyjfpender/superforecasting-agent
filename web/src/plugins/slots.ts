/**
 * Plugin slot registry.
 *
 * Plugins can inject components into named locations in the app shell
 * (header-left, sidebar, backdrop, etc.) by calling
 * `window.__SUPERFORECASTING_AGENT_PLUGINS__.registerSlot(pluginName, slotName, Component)`
 * from their JS bundle. The older `window.__HERMES_PLUGINS__` namespace remains
 * available as a compatibility alias. Multiple plugins can populate the same
 * slot and render stacked in registration order.
 *
 * The canonical slot names are documented in `KNOWN_SLOT_NAMES` below. The
 * registry accepts any string so plugin ecosystems can define their own
 * slots; the shell only renders `<PluginSlot name="..." />` for the slots
 * it knows about. Some inherited slot names are compatibility aliases that
 * render through canonical forecast-native slots.
 */

import React, { Fragment, useEffect, useState } from "react";

/** Slot locations the built-in shell renders. Plugins declaring any of
 *  these in their manifest's `slots` field get wired in automatically.
 *
 *  Shell-wide slots:
 *  - `backdrop`         — rendered inside `<Backdrop />`, above the noise layer
 *  - `header-left`      — injected before the app brand in the top bar
 *  - `header-right`     — injected before the theme/language switchers
 *  - `header-banner`    — injected below the top nav bar, full-width
 *  - `sidebar`          — the cockpit sidebar rail (only rendered when
 *                         `layoutVariant === "cockpit"`)
 *  - `pre-main`         — rendered above the route outlet (inside `<main>`)
 *  - `post-main`        — rendered below the route outlet (inside `<main>`)
 *  - `footer-left`      — replaces the left footer cell content
 *  - `footer-right`     — replaces the right footer cell content
 *  - `overlay`          — fixed-position layer above everything else;
 *                         useful for chrome (scanlines, vignettes) the
 *                         theme's customCSS can't achieve alone
 *
 *  Page-scoped slots (rendered inside a specific built-in page — use these
 *  to inject widgets, cards, or toolbars into existing pages without
 *  overriding the whole route):
 *  - `sessions:top`     — top of /sessions page (above session list)
 *  - `sessions:bottom`  — bottom of /sessions page
 *  - `analytics:top`    — top of /analytics page
 *  - `analytics:bottom` — bottom of /analytics page
 *  - `logs:top`         — top of /logs page (above filter toolbar)
 *  - `logs:bottom`      — bottom of /logs page (below log viewer)
 *  - `cron:top`         — top of /cron page
 *  - `cron:bottom`      — bottom of /cron page
 *  - `skills:top`       — top of /skills page
 *  - `skills:bottom`    — bottom of /skills page
 *  - `plugins:top`       — top of /plugins page
 *  - `plugins:bottom`    — bottom of /plugins page
 *  - `config:top`       — top of /config page
 *  - `config:bottom`    — bottom of /config page
 *  - `env:top`          — top of /env (Keys) page
 *  - `env:bottom`       — bottom of /env (Keys) page
 *  - `docs:top`         — top of /docs page (above the docs iframe)
 *  - `docs:bottom`      — bottom of /docs page
 *  - `forecast-desk:top`    — top of the embedded Forecast Desk page
 *  - `forecast-desk:bottom` — bottom of the embedded Forecast Desk page
 *
 *  Compatibility aliases accepted by the registry:
 *  - `chat:top`         — legacy alias rendered through `forecast-desk:top`
 *  - `chat:bottom`      — legacy alias rendered through `forecast-desk:bottom`
 */
export const KNOWN_SLOT_NAMES = [
  // Shell-wide
  "backdrop",
  "header-left",
  "header-right",
  "header-banner",
  "sidebar",
  "pre-main",
  "post-main",
  "footer-left",
  "footer-right",
  "overlay",
  // Page-scoped
  "sessions:top",
  "sessions:bottom",
  "analytics:top",
  "analytics:bottom",
  "logs:top",
  "logs:bottom",
  "cron:top",
  "cron:bottom",
  "skills:top",
  "skills:bottom",
  "plugins:top",
  "plugins:bottom",
  "config:top",
  "config:bottom",
  "env:top",
  "env:bottom",
  "docs:top",
  "docs:bottom",
  "forecast-desk:top",
  "forecast-desk:bottom",
  "chat:top",
  "chat:bottom",
] as const;

export type KnownSlotName = (typeof KNOWN_SLOT_NAMES)[number];

type SlotListener = () => void;

interface SlotEntry {
  plugin: string;
  component: React.ComponentType;
}

const SLOT_RENDER_ALIASES: Record<string, string[]> = {
  "forecast-desk:top": ["chat:top"],
  "forecast-desk:bottom": ["chat:bottom"],
};

/** Map<slotName, SlotEntry[]>. Entries are appended in registration order. */
const _slotRegistry: Map<string, SlotEntry[]> = new Map();
const _slotListeners: Set<SlotListener> = new Set();

function _notifySlots() {
  for (const fn of _slotListeners) {
    try {
      fn();
    } catch {
      /* ignore */
    }
  }
}

/** Register a component for a slot. Called by plugin bundles via
 *  `window.__SUPERFORECASTING_AGENT_PLUGINS__.registerSlot(...)`.
 *
 *  If the same (plugin, slot) pair is registered twice, the later call
 *  replaces the earlier one — this matches how React HMR expects plugin
 *  re-mounts to behave. */
export function registerSlot(
  plugin: string,
  slot: string,
  component: React.ComponentType,
): void {
  const existing = _slotRegistry.get(slot) ?? [];
  const filtered = existing.filter((e) => e.plugin !== plugin);
  filtered.push({ plugin, component });
  _slotRegistry.set(slot, filtered);
  _notifySlots();
}

/** Read current entries for a slot. Returns a copy so callers can't mutate
 *  registry state. */
export function getSlotEntries(slot: string): SlotEntry[] {
  return (_slotRegistry.get(slot) ?? []).slice();
}

function getRenderableSlotEntries(slot: string): SlotEntry[] {
  const slotNames = [slot, ...(SLOT_RENDER_ALIASES[slot] ?? [])];
  const seenPlugins = new Set<string>();
  const entries: SlotEntry[] = [];

  for (const slotName of slotNames) {
    for (const entry of _slotRegistry.get(slotName) ?? []) {
      if (seenPlugins.has(entry.plugin)) continue;
      seenPlugins.add(entry.plugin);
      entries.push(entry);
    }
  }

  return entries;
}

/** Subscribe to registry changes. Returns an unsubscribe function. */
export function onSlotRegistered(fn: SlotListener): () => void {
  _slotListeners.add(fn);
  return () => {
    _slotListeners.delete(fn);
  };
}

/** Clear a specific plugin's slot registrations. Useful for HMR /
 *  plugin reload flows — not wired in by default. */
export function unregisterPluginSlots(plugin: string): void {
  let changed = false;
  for (const [slot, entries] of _slotRegistry.entries()) {
    const kept = entries.filter((e) => e.plugin !== plugin);
    if (kept.length !== entries.length) {
      changed = true;
      if (kept.length === 0) _slotRegistry.delete(slot);
      else _slotRegistry.set(slot, kept);
    }
  }
  if (changed) _notifySlots();
}

interface PluginSlotProps {
  /** Slot identifier (e.g. `"sidebar"`, `"header-left"`). */
  name: string;
  /** Optional content rendered when no plugins have claimed the slot.
   *  Useful for built-in defaults the plugin would replace. */
  fallback?: React.ReactNode;
}

/** Render all components registered for a given slot, stacked in order.
 *
 *  Component re-renders when the slot registry changes so plugins that
 *  arrive after initial mount show up without a manual refresh. Canonical
 *  forecast-desk slots also render entries registered under legacy `chat:*`
 *  aliases so old plugins keep working without the page mounting old slot
 *  names directly. */
export function PluginSlot({ name, fallback }: PluginSlotProps) {
  const [entries, setEntries] = useState<SlotEntry[]>(() => getRenderableSlotEntries(name));

  useEffect(() => {
    // Pick up anything registered between the initial `useState` call
    // and the first effect tick, then subscribe for future changes.
    setEntries(getRenderableSlotEntries(name));
    const unsub = onSlotRegistered(() => setEntries(getRenderableSlotEntries(name)));
    return unsub;
  }, [name]);

  if (entries.length === 0) {
    return fallback ? React.createElement(Fragment, null, fallback) : null;
  }

  return React.createElement(
    Fragment,
    null,
    ...entries.map((entry) =>
      React.createElement(entry.component, { key: entry.plugin }),
    ),
  );
}
