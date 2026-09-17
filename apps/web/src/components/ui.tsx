import { AlertCircle, Inbox, RefreshCw } from "lucide-react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: React.ReactNode }) {
  return <header className="page-heading">
    <div className="page-heading-copy">
      {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
      <h1>{title}</h1>{description && <p>{description}</p>}
    </div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="empty-state"><Inbox size={26} strokeWidth={1.5} aria-hidden="true" /><strong>{title}</strong><p>{description}</p>{action}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="error-state" role="alert"><AlertCircle size={20} aria-hidden="true" /><div><strong>加载失败</strong><p>{message}</p></div>{onRetry && <button className="btn btn-sm" type="button" onClick={onRetry}><RefreshCw size={15} />重试</button>}</div>;
}
