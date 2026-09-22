/**
 * Right-hand drawer for drill-down and record detail — DESIGN.md §4.
 *
 * 560px, slides in over 140ms, closes on Escape or backdrop click. Focus moves
 * into the drawer on open and returns to the trigger on close.
 */
import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

export function Drawer({
  open,
  title,
  description,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreFocusTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      restoreFocusTo.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        className="absolute inset-0 bg-ink/20"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative flex h-full w-drawer max-w-full flex-col border-l border-line bg-surface shadow-drawer"
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-card py-3">
          <div className="min-w-0">
            <h2 className="text-title font-semibold text-ink">{title}</h2>
            {description && (
              <div className="mt-0.5 text-caption text-ink-muted">{description}</div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded border border-line bg-surface px-2 py-1 text-body text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
          >
            Close
          </button>
        </header>
        <div className="flex-1 overflow-auto px-card py-card">{children}</div>
      </div>
    </div>
  );
}
