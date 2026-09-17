"use client";

import { cloneElement, ReactElement, ReactNode, RefObject, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

const focusableSelector = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function Drawer({
  title,
  description,
  onClose,
  closeLabel,
  busy = false,
  children,
  widthClass = "w-[860px] max-w-[95vw]",
  initialFocusRef,
  headerAfter,
}: {
  title: string;
  description?: string;
  onClose: () => void;
  closeLabel: string;
  busy?: boolean;
  children: ReactNode;
  widthClass?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  headerAfter?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const titleId = useId();
  const descriptionId = useId();
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const shell = document.querySelector<HTMLElement>("[data-app-shell]");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    shell?.setAttribute("inert", "");
    window.setTimeout(() => (initialFocusRef?.current ?? closeRef.current)?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(focusableSelector));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      shell?.removeAttribute("inert");
      window.setTimeout(() => previousFocus.current?.focus(), 0);
    };
  }, [initialFocusRef]);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className="product-drawer-backdrop fixed inset-0 z-50 flex justify-end bg-black/30"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !busy) onClose();
      }}
    >
      <div
        ref={panelRef}
        className={`product-drawer h-full ${widthClass} overflow-y-auto bg-white`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
      >
        <div className="sticky top-0 z-20 flex items-center justify-between border-b bg-white p-5">
          <div>
            <h2 id={titleId} className="text-lg font-bold">{title}</h2>
            {description && <p id={descriptionId} className="text-xs text-slate-500">{description}</p>}
          </div>
          <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} disabled={busy} aria-label={closeLabel}><X /></button>
        </div>
        {headerAfter}
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Tabs({
  items,
  value,
  onChange,
  label,
  panelId = "active-tab-panel",
}: {
  items: Array<{ value: string; label: string }>;
  value: string;
  onChange: (value: string) => void;
  label: string;
  panelId?: string;
}) {
  const baseId = useId();
  const move = (current: number, direction: number) => {
    const next = (current + direction + items.length) % items.length;
    onChange(items[next].value);
    document.getElementById(`${baseId}-tab-${next}`)?.focus();
  };
  return (
    <div className="product-tabs sticky top-[77px] z-10 flex border-b bg-white px-5" role="tablist" aria-label={label}>
      {items.map((item, index) => (
        <button
          id={`${baseId}-tab-${index}`}
          key={item.value}
          type="button"
          role="tab"
          aria-selected={value === item.value}
          aria-controls={panelId}
          tabIndex={value === item.value ? 0 : -1}
          onClick={() => onChange(item.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") move(index, 1);
            else if (event.key === "ArrowLeft") move(index, -1);
            else if (event.key === "Home") move(0, 0);
            else if (event.key === "End") move(items.length - 1, 0);
            else return;
            event.preventDefault();
          }}
          className={`px-4 py-3 text-sm font-semibold ${value === item.value ? "border-b-2 border-brand text-slate-900" : "text-slate-500"}`}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function FormField({
  id,
  label,
  help,
  error,
  required,
  children,
  className = "",
}: {
  id: string;
  label: string;
  help?: string;
  error?: string;
  required?: boolean;
  children: ReactElement<Record<string, unknown>>;
  className?: string;
}) {
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;
  const control = cloneElement(children, {
    id,
    required,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
  });
  return (
    <div className={`form-field ${className}`}>
      <label className="text-sm font-semibold" htmlFor={id}>{label}{required && <span aria-hidden="true"> *</span>}</label>
      {control}
      {help && <small id={helpId} className="field-help">{help}</small>}
      {error && <p id={errorId} className="field-error">{error}</p>}
    </div>
  );
}

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" | "info" }) {
  const toneClass = { neutral: "", success: "badge-green", warning: "badge-amber", danger: "badge-red", info: "badge-blue" }[tone];
  return <span className={`badge ${toneClass}`}>{children}</span>;
}
