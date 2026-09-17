"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";

type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  action?: () => Promise<unknown>;
};
type PendingConfirm = ConfirmOptions & { resolve: (value: boolean) => void };
const ConfirmContext = createContext<((options: ConfirmOptions) => Promise<boolean>) | null>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPending({ ...options, resolve });
  }), []);

  const settle = useCallback((value: boolean) => {
    setPending((current) => {
      current?.resolve(value);
      return null;
    });
    window.setTimeout(() => previousFocus.current?.focus(), 0);
  }, []);

  const submit = useCallback(async () => {
    if (!pending || busy) return;
    if (!pending.action) {
      settle(true);
      return;
    }
    setBusy(true);
    busyRef.current = true;
    setError("");
    try {
      await pending.action();
      settle(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败，请重试");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }, [busy, pending, settle]);

  useEffect(() => {
    if (!pending) return;
    setBusy(false);
    busyRef.current = false;
    setError("");
    const shell = document.querySelector<HTMLElement>("[data-app-shell]");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    shell?.setAttribute("inert", "");
    window.setTimeout(() => cancelRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (busyRef.current) return;
        event.preventDefault();
        settle(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
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
    };
  }, [pending, settle]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && typeof document !== "undefined" && createPortal(
        <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.currentTarget === event.target && !busy) settle(false);
        }}>
          <div ref={dialogRef} className="dialog-panel" role="alertdialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby={pending.description ? "confirm-dialog-description" : undefined}>
            <div className={`dialog-symbol ${pending.tone === "danger" ? "is-danger" : ""}`} aria-hidden="true"><AlertTriangle size={20} strokeWidth={1.8} /></div>
            <div className="dialog-copy">
              <h2 id="confirm-dialog-title">{pending.title}</h2>
              {pending.description && <p id="confirm-dialog-description">{pending.description}</p>}
            </div>
            {error && <p className="dialog-error" role="alert">{error}</p>}
            <div className="dialog-actions">
              <button ref={cancelRef} className="btn" type="button" disabled={busy} onClick={() => settle(false)}>{pending.cancelLabel ?? "取消"}</button>
              <button className={`btn ${pending.tone === "danger" ? "btn-danger" : "btn-primary"}`} type="button" disabled={busy} aria-busy={busy} onClick={submit}>{busy ? "正在处理…" : pending.confirmLabel ?? "确认"}</button>
            </div>
          </div>
        </div>, document.body,
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error("useConfirm must be used inside ConfirmProvider");
  return context;
}
