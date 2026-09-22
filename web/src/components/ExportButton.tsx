/**
 * The export control that sits on every panel — RFP area 8.
 *
 * One spelling, shared by the dashboards, the assistant and the sandbox, so a
 * panel cannot grow its own export affordance.
 */
export function ExportButton({
  onClick,
  label = 'Export',
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
    >
      {label}
    </button>
  );
}
