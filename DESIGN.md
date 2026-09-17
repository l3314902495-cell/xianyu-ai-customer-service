---
name: Xianyu AI Customer Service
description: A high-density operations console for live Xianyu conversations, product knowledge and controlled AI assistance.
version: 1.0.0
framework: nextjs
source: apps/web/app/globals.css
---

# Design system

## Product character

The interface should feel like a calm live operations room: dependable under pressure, dense without becoming noisy, and human enough for a seller who spends hours in it. It is not a generic analytics dashboard. The visual hierarchy follows the real message path: incoming buyer signal, product context, AI decision, and operator action.

The single signature element is the **semantic amber edge**: a narrow amber edge used only for selected navigation and active AI-control moments. Decorative line-and-dot motifs, English dashboard eyebrows and ornamental status graphics are prohibited because operators must understand every mark immediately.

## Canonical ownership

`apps/web/app/globals.css` is the runtime source of truth. This document records the accepted decisions and maps semantic intent to those CSS custom properties. New pages must consume the semantic tokens rather than introduce one-off colors or elevations.

## Color

```json
{
  "canvas": "#F2F4F3",
  "surface": "#FFFFFF",
  "surface-subtle": "#F7F8F7",
  "surface-muted": "#ECF0ED",
  "surface-raised": "#FFFFFF",
  "ink": "#17212B",
  "ink-soft": "#4C5968",
  "ink-faint": "#65717D",
  "shell": "#101820",
  "shell-muted": "#1B2530",
  "line": "#E0E5E2",
  "line-strong": "#C8D0CB",
  "signal": "#F5B700",
  "signal-strong": "#D99A00",
  "signal-soft": "#FFF8DF",
  "success": "#147A5A",
  "success-soft": "#ECF8F2",
  "info": "#2866A5",
  "info-soft": "#EEF5FA",
  "warning": "#A86112",
  "danger": "#B83A36",
  "danger-soft": "#FFF3F1",
  "focus": "#E8A900",
  "on-dark": "#F6F7F4"
}
```

Amber is a control signal, not a background theme. Jade, rust and blue are reserved for state meaning. Body text must meet WCAG 2.2 AA contrast on its surface.

## Typography

```json
{
  "display": {"family": "Segoe UI Variable, PingFang SC, Microsoft YaHei UI, Microsoft YaHei, sans-serif", "size": "2rem", "lineHeight": "1.2", "weight": "650", "letterSpacing": "-0.02em"},
  "heading-1": {"size": "1.5rem", "lineHeight": "1.3", "weight": "650", "letterSpacing": "-0.015em"},
  "heading-2": {"size": "1.125rem", "lineHeight": "1.4", "weight": "650", "letterSpacing": "-0.01em"},
  "body": {"family": "Segoe UI Variable, PingFang SC, Microsoft YaHei UI, Microsoft YaHei, sans-serif", "size": "0.9375rem", "lineHeight": "1.65", "weight": "430"},
  "label": {"size": "0.8125rem", "lineHeight": "1.4", "weight": "620", "letterSpacing": "0.01em"},
  "caption": {"size": "0.75rem", "lineHeight": "1.5", "weight": "470"},
  "data": {"family": "JetBrains Mono, SFMono-Regular, Consolas, monospace", "size": "0.875rem", "lineHeight": "1.45", "weight": "560", "letterSpacing": "-0.02em"}
}
```

Operational metrics use the body face with tabular numerals so zeroes stay immediately legible; IDs and technical diagnostics use the data face. Long Chinese content uses the body face and must never be artificially letter-spaced.

## Spacing and layout

```json
{
  "space-1": "0.25rem",
  "space-2": "0.5rem",
  "space-3": "0.75rem",
  "space-4": "1rem",
  "space-5": "1.25rem",
  "space-6": "1.5rem",
  "space-8": "2rem",
  "space-10": "2.5rem",
  "space-12": "3rem"
}
```

Desktop pages use a 12-column mental grid, a 64px top command bar, and a 238px navigation column. At laptop widths the sidebar becomes a 72px rail. The application intentionally supports desktop and laptop browsers only; smaller windows retain the desktop shell and may scroll horizontally rather than introducing a second mobile navigation system. Data tables scroll horizontally rather than compress columns beyond recognition.

## Shape and elevation

```json
{
  "radius-sm": "0.375rem",
  "radius-md": "0.625rem",
  "radius-lg": "0.875rem",
  "radius-pill": "999px",
  "shadow-raised": "0 12px 32px rgba(16, 24, 32, 0.07)",
  "shadow-overlay": "0 24px 64px rgba(16, 24, 32, 0.18)"
}
```

Default information regions are flat and separated by soft neutral lines or spacing. Bounded operational groups may use the shared 14px radius, but never a floating-card grid. Elevation is reserved for overlays, popovers, menus and the active conversation composer.

## Component language

- Navigation is dark, quiet and information-first. Selection uses a pale text change plus a narrow amber edge.
- Buttons use three levels: solid ink primary, bordered secondary, and text/ghost tertiary. Destructive actions are rust and require confirmation when irreversible.
- Inputs use visible labels, 40px minimum height, a 2px focus ring, persistent error copy and no placeholder-only labeling.
- Cards are bounded regions only when grouping is necessary; their borders stay low-contrast and a page must not become a grid of identical floating rounded boxes.
- Conversation surfaces use white for buyer messages, a restrained amber wash for AI messages and a cool blue wash for human messages. Large yellow fills are prohibited.
- Tables use sticky muted headers, clear row hover, tabular numerals and a horizontal overflow owner.
- Status badges use tinted semantic backgrounds and never rely on color alone.
- Dialogs and drawers trap focus, restore focus, close on Escape, lock background scroll and own their z-index layer.
- Toasts are limited to three visible items, announced by a live region, and never replace inline validation.

## Interaction states

All interactive controls must provide hover, focus-visible, active, loading and disabled states. Motion uses three shared runtime tokens: 120ms for direct feedback, 180ms for overlays and semantic signals, and 260ms for route or section entry. Direct manipulation uses the standard easing curve; entrances use the shared ease-out curve.

Route content enters once with a short fade and 7px vertical lift. Dashboard regions may follow with a restrained 40ms stagger so the reading order is perceptible without delaying operation. The semantic amber navigation edge grows into place; live-status dots may pulse slowly; popovers and toasts enter from the edge they are anchored to. Motion must not loop except for truthful live or loading state, must not move primary controls, and must never be required to understand state.

Respect `prefers-reduced-motion`: decorative and entrance animation is removed completely, while content and state remain immediately available.

## Responsive rules

- `>= 1280px`: full three-pane customer service workspace and persistent expanded sidebar.
- `1024–1279px`: compact navigation rail; secondary information may move below or become a detail panel.
- `< 1024px`: unsupported as a primary operating surface; retain the desktop shell without a separate mobile component or state model.

No page may depend on viewport-wide fixed pixel columns. Long names truncate with an accessible title; long message content wraps; large numbers use tabular numerals.

## Accessibility baseline

Target WCAG 2.2 AA. Every icon-only button requires an accessible name. Focus order follows visual order. Touch targets are at least 44px on touch layouts. Forced-colors mode retains boundaries and selection state.
