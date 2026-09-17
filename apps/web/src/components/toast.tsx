"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";

type ToastTone = "success" | "error" | "info";
type ToastInput = { title: string; description?: string; tone?: ToastTone; duration?: number };
type ToastItem = ToastInput & { id: number };
const ToastContext = createContext<((toast: ToastInput) => void) | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((current) => current.filter((item) => item.id !== id)), []);
  const push = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    setItems((current) => [...current.filter((item) => item.title !== input.title || item.description !== input.description), { ...input, id }].slice(-3));
    window.setTimeout(() => dismiss(id), input.duration ?? 4200);
  }, [dismiss]);
  const icons = useMemo(() => ({ success: <CheckCircle2 size={18} />, error: <CircleAlert size={18} />, info: <Info size={18} /> }), []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-region" aria-live="polite" aria-relevant="additions removals">
        {items.map((item) => {
          const tone = item.tone ?? "info";
          return <div key={item.id} className={`toast toast-${tone}`} role={tone === "error" ? "alert" : "status"}>
            <span className="toast-icon" aria-hidden="true">{icons[tone]}</span>
            <span className="toast-copy"><strong>{item.title}</strong>{item.description && <span>{item.description}</span>}</span>
            <button type="button" className="icon-btn" onClick={() => dismiss(item.id)} aria-label="关闭通知"><X size={16} /></button>
          </div>;
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
