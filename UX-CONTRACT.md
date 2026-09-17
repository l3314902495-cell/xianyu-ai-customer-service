# UX contract

## Product and users

This is a single-shop Xianyu AI customer-service control center for sellers and operators. The primary user monitors incoming chats, verifies product context, controls AI automation, handles exceptions and maintains product knowledge. The supported product surface is desktop and laptop. Mobile and tablet-specific navigation or workflow variants are intentionally outside the product scope.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | Native HTML `select` | `apps/web/app/globals.css` `.input` | Single and disabled | Keyboard selection, visible label and focus ring |
| Select | Native HTML select | apps/web/app/globals.css | native | Keyboard and popup verification |
| Form | `FormField` plus application HTML form | `apps/web/src/components/interaction.tsx` | Create, edit and test | `noValidate`, associated error, first-error focus and pending action |
| Dialog | `ConfirmDialogProvider` | `apps/web/src/components/confirm-dialog.tsx` | Destructive and standard confirmation | Initial safe focus, Tab containment, Escape and restoration |
| Drawer | `Drawer` | `apps/web/src/components/interaction.tsx` | Edit, publish and inspect | Focus trap/restoration, dirty guard, scroll lock and busy dismissal guard |
| Tabs | `Tabs` | `apps/web/src/components/interaction.tsx` | Drawer sections | `tablist` semantics and Arrow/Home/End keyboard model |
| Status | `StatusBadge` | `apps/web/src/components/interaction.tsx` | Neutral, success, warning and danger | Text always accompanies color |
| Toast | `ToastProvider` | `apps/web/src/components/toast.tsx` | Success, error and information | Live-region announcement, dedupe and maximum of three |
| Scrollbar | Application CSS | `apps/web/app/globals.css` | Document, table, workspace panel | No nested arbitrary scroll and no horizontal viewport overflow |
| CRUD state | React Query views | Existing view modules and API client | Loading, empty, error, partial and ready | Stable geometry, retry route and local pending state |
| CRUD | React Query mutation flows | apps/web/src/views and apps/web/src/lib/api.ts | return / stay | Full create, update and delete flow |

## Authoritative sources

- Existing business scope and acceptance criteria: `README.md` and `TASKS.md`.
- Runtime API behavior: FastAPI routes and schemas under `apps/api/app/api` and `apps/api/app/schemas`.
- Persistent domain state: SQLAlchemy models under `apps/api/app/models.py` and migrations under `apps/api/alembic`.
- Frontend behavior: routes under `apps/web/app` and view components under `apps/web/src/components/views`.

UI changes may reorganize presentation but must not rename API fields, alter backend state transitions, or bypass AI send guards.

## Core journeys

1. Administrator signs in and lands on the operations dashboard.
2. Operator sees live service health, urgent conversations and recent activity.
3. Operator enters the three-part service workspace: conversation queue, messages, product/AI context.
4. Operator may take over, send or edit an AI suggestion, resolve a knowledge gap, then restore AI.
5. Operator maintains each product's data, knowledge, FAQ, prompt and AI status.
6. Operator configures the provider and tests connectivity without exposing the full API key.
7. Operator connects or inspects Xianyu accounts and can synchronize supported external data.
8. Operator may publish a new product through a connected, user-owned experimental web account after a dedicated review step.

## Navigation contract

- Desktop uses persistent grouped navigation.
- Laptop may collapse to an icon rail while preserving tooltips/titles.
- Narrow windows keep the desktop navigation model; the application does not maintain a second mobile drawer state.
- The current route is indicated visually and through `aria-current="page"`.
- Page title and document title follow the active route.

## Forms

- All forms use persistent labels and `noValidate`; server and client errors render inline.
- Primary submission remains visible near the final field or in a stable action footer.
- While submitting, controls prevent duplicate submission and the primary action communicates progress.
- Native `<select>` is the owned select implementation for V1. The operating-system popup behavior is accepted; the closed trigger is styled consistently and remains keyboard accessible.
- Textareas do not expose uncontrolled resize handles; layouts provide intentional minimum heights and content scrolling.
- Secret fields support show/hide, never return saved secrets in full, and do not overwrite a saved value when left blank.
- Real product publishing is a two-step form: edit, then review. The final button names the external action and remains pessimistic until Xianyu returns a product ID.

## External product publishing

- Only `experimental-web` accounts with a confirmed connected state and encrypted scan-login credential may publish.
- Publication is an externally visible, non-idempotent side effect. Every request carries a client idempotency key, creates an audit record before network work, and is limited to one attempt per account per minute.
- The system uploads 1–9 validated JPG, PNG or WebP images, asks Xianyu to identify the category, and sends one final publish request. It never retries that final request automatically.
- A timeout after the final request is recorded as `UNKNOWN`; the operator is instructed to synchronize or inspect Xianyu before attempting again.
- Verification, session expiry, rate limiting, or risk-control responses stop the operation. The system does not solve or bypass platform challenges.
- Success requires a returned Xianyu product ID. Only then is the local product created and the shared success toast shown.

## Dialogs, drawers and popovers

- Browser-native `alert`, `confirm` and `prompt` are prohibited.
- App dialogs have a labelled title, optional description, initial focus on the safest action, Tab containment, Escape dismissal unless a non-interruptible operation is active, backdrop click dismissal when safe, scroll lock and focus restoration.
- Drawers own their internal scroll region. Sticky headers and footers stay within that region.
- Popovers close on outside interaction and Escape and are positioned within the viewport.

## Async and data resilience

- Initial loads show skeletons that resemble final geometry.
- Empty states explain why the region is empty and offer one relevant action when available.
- Errors appear at the affected region with a retry path; existing stale data remains visible where safe.
- Mutations disable only the affected action, show pending state, surface success through a toast or persistent status, and invalidate the relevant React Query keys.
- Background WebSocket refresh must not steal focus, reset an open form, or move the user's scroll position.
- Toasts are capped at three, deduplicated by message, and announced by a polite live region. Destructive failures use assertive announcement.

## Tables and collections

- Products, conversations, messages, AI logs and operation logs use server-owned cursor pagination with stable `(timestamp, id)` ordering. The client keeps loaded pages visible and offers an explicit “load more” action.
- Search, filters and sort state remain visible and understandable. Empty filtered results differ from an empty dataset.
- Row actions remain reachable by keyboard. Critical destructive actions require an app dialog.
- Cursor requests preserve active filters; refresh may replace loaded pages but must not duplicate or omit equal-timestamp rows.

## Customer-service workspace

- Desktop: queue, chat and context are visible together.
- Laptop: queue and chat remain primary; context may be hidden when the navigation is in rail mode.
- Message history owns its scroll. The product/context panel owns a separate scroll and never disappears because the document was scrolled.
- Incoming events may play the user's enabled sound but cannot auto-scroll if the operator is reading earlier history; show an unread/new-message affordance instead.
- Opening a conversation or choosing “全部已读” advances a browser-local read marker only. It must not call a backend read endpoint or change Xianyu platform state; new server updates after that marker become locally unread again.
- Seller message bubbles show Xianyu read-receipt state only from captured platform events. Local read markers never alter “闲鱼已读 / 闲鱼未读 / 闲鱼状态未知”.

## Status and safety semantics

- Green: connected/sent/safe active state.
- Amber: AI active control, pending attention or medium caution.
- Rust/red: failure, high risk, destructive action or disconnected state.
- Blue: human handling and neutral information.
- Every status includes text or an icon label; color is never the only carrier.
- Global AI control and bulk product takeover controls retain their existing backend behavior and confirmation requirements.

## Responsive and overflow ownership

- Global document scroll is used for standard pages.
- Conversation workspace uses explicit nested scroll owners on every supported desktop/laptop viewport.
- Tables own horizontal overflow; dialogs/drawers own vertical overflow; nested arbitrary scroll areas are prohibited.
- Sticky content must account for the 64px command bar and never overlap focused fields.

## Verification evidence

Required frontend commands:

```text
pnpm --filter @xianyu/web lint
pnpm --filter @xianyu/web typecheck
pnpm --filter @xianyu/web test
pnpm --filter @xianyu/web build
```

Browser verification covers login, dashboard, conversations, products, account management and model settings at desktop and laptop widths. Keyboard checks cover navigation, dialogs, forms and Escape/focus restoration.
