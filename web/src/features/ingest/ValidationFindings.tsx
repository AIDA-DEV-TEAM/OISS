/**
 * Validation results, grouped by rule.
 *
 * Defaults to errors and warnings. The info findings — overwhelmingly
 * STRUCTURALLY_ABSENT, meaning a crop that is not grown or not priced in that
 * district — sit behind a visible toggle, because the separation between "no
 * value here" and "this series does not exist" is the point worth showing, not
 * something to bury.
 *
 * Works from a stored dataset version (detail fetched on expand) or from an
 * upload result (detail already in hand), through one presentational path.
 */
import { useMemo, useState } from 'react';

import type { RuleSummary, ValidationFinding } from '@/api/client';
import { useFindings } from '@/api/hooks';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { Badge, Card, Figure, SeverityChip, cn } from '@/components/primitives';
import type { Severity } from '@/components/primitives';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { formatCount, humanRule, parseRowRef } from '@/lib/format';

const DETAIL_PAGE_SIZE = 50;

/** Explains why a rule exists, in the words a reviewer would want. */
const RULE_NOTE: Record<string, string> = {
  UNKNOWN_DISTRICT: 'Name absent from the district alias table. Never guessed at.',
  UNKNOWN_CROP: 'Name absent from the crop master.',
  TYPE_MISMATCH: 'Non-numeric text where a number is required.',
  SCHEMA_MISMATCH: 'A declared column is missing, or an extra one appeared.',
  DUPLICATE_KEY: "More than one row on the fact's natural key.",
  OUT_OF_RANGE: 'Negative or implausible value for a yield or a price.',
  MISSING_VALUE: 'A gap inside an otherwise populated series.',
  TOTAL_ROW_IN_DETAIL: 'A state total sitting among district rows; excluded from district aggregates.',
  IDENTITY_MISMATCH: 'Area × yield differs from production by more than 2%.',
  CROSS_SOURCE_MISMATCH: 'The same measure differs between two DE&S sources.',
  MSP_SUBSTITUTED: 'Paddy price is the Minimum Support Price, not an observed market price.',
  STRUCTURALLY_ABSENT:
    'No value in any year of any source: the crop is not grown or not priced there. Not a data-quality problem.',
  UNKNOWN_BLOCK: 'Block spelling with no match in the coded block list; loaded with a null block id.',
};

export interface FindingsSource {
  summary: RuleSummary[];
  /** Set for a stored version: detail rows are fetched per rule. */
  versionId?: string;
  /** Set for an upload: detail rows are already present (capped by the backend). */
  localFindings?: ValidationFinding[];
  localCapped?: boolean;
}

function detailColumns(): Array<Column<ValidationFinding>> {
  return [
    {
      key: 'row',
      header: 'Row',
      numeric: true,
      width: '72px',
      render: (finding) => {
        const { row } = parseRowRef(finding.row_ref);
        return <Figure className="text-ink-muted">{row ?? '—'}</Figure>;
      },
    },
    {
      key: 'series',
      header: 'Series',
      render: (finding) => {
        const { series } = parseRowRef(finding.row_ref);
        if (series.length === 0) {
          return <span className="text-ink-subtle">—</span>;
        }
        return (
          <span className="flex flex-wrap gap-x-3 gap-y-0.5">
            {series.map((part) => (
              <span key={part.key} className="whitespace-nowrap">
                <span className="text-ink-subtle">{part.key}</span>{' '}
                <span className="text-ink">{part.value}</span>
              </span>
            ))}
          </span>
        );
      },
    },
    {
      key: 'column',
      header: 'Column',
      width: '160px',
      render: (finding) => finding.column_name ?? <span className="text-ink-subtle">—</span>,
    },
    {
      key: 'observed',
      header: 'Offending value',
      width: '160px',
      render: (finding) =>
        finding.observed_value === null || finding.observed_value === undefined ? (
          <span className="text-ink-subtle">(blank)</span>
        ) : (
          <code className="rounded bg-surface-alt px-1 py-0.5 text-caption text-ink">
            {finding.observed_value}
          </code>
        ),
    },
    {
      key: 'message',
      header: 'Message',
      render: (finding) => <span className="text-ink-muted">{finding.message}</span>,
    },
  ];
}

function RuleDetail({
  rule,
  versionId,
  localFindings,
  localCapped,
}: {
  rule: RuleSummary;
  versionId?: string;
  localFindings?: ValidationFinding[];
  localCapped?: boolean;
}) {
  const remote = useFindings(versionId, {
    ruleCode: rule.rule_code,
    size: DETAIL_PAGE_SIZE,
  });

  if (localFindings) {
    const rows = localFindings.filter((f) => f.rule_code === rule.rule_code);
    return (
      <>
        <DataTable
          columns={detailColumns()}
          rows={rows}
          rowKey={(_, index) => `${rule.rule_code}-${index}`}
          compact
          maxHeight="320px"
          caption={`Findings for ${rule.rule_code}`}
          emptyMessage="No row-level detail was returned for this rule."
        />
        {localCapped && rows.length < rule.finding_count && (
          <p className="mt-2 text-caption text-ink-subtle">
            Showing <Figure>{formatCount(rows.length)}</Figure> of{' '}
            <Figure>{formatCount(rule.finding_count)}</Figure>. The upload response caps
            row-level detail per rule; the full set is stored against the dataset version.
          </p>
        )}
      </>
    );
  }

  if (remote.isPending) return <LoadingState label="Loading findings" rows={3} />;
  if (remote.isError)
    return <ErrorState error={remote.error} onRetry={() => remote.refetch()} compact />;
  if (!remote.data) return null;

  return (
    <>
      <DataTable
        columns={detailColumns()}
        rows={remote.data.items}
        rowKey={(_, index) => `${rule.rule_code}-${index}`}
        compact
        maxHeight="320px"
        caption={`Findings for ${rule.rule_code}`}
        emptyMessage="No row-level detail for this rule."
      />
      {remote.data.total > remote.data.items.length && (
        <p className="mt-2 text-caption text-ink-subtle">
          Showing the first <Figure>{formatCount(remote.data.items.length)}</Figure> of{' '}
          <Figure>{formatCount(remote.data.total)}</Figure> findings for this rule.
        </p>
      )}
    </>
  );
}

function RuleRow({
  rule,
  expanded,
  onToggle,
  versionId,
  localFindings,
  localCapped,
}: {
  rule: RuleSummary;
  expanded: boolean;
  onToggle: () => void;
  versionId?: string;
  localFindings?: ValidationFinding[];
  localCapped?: boolean;
}) {
  const note = RULE_NOTE[rule.rule_code];
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-3 px-card py-2.5 text-left transition-colors duration-state hover:bg-surface-alt"
      >
        <span
          aria-hidden="true"
          className={cn(
            'mt-1 shrink-0 text-caption text-ink-subtle transition-transform duration-state',
            expanded && 'rotate-90',
          )}
        >
          ▶
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-body font-medium text-ink">
              {humanRule(rule.rule_code)}
            </span>
            <SeverityChip severity={rule.severity as Severity} count={rule.finding_count} />
            <code className="text-caption text-ink-subtle">{rule.rule_code}</code>
          </span>
          {note && <span className="mt-0.5 block text-caption text-ink-muted">{note}</span>}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-line bg-surface-alt px-card py-3">
          <RuleDetail
            rule={rule}
            versionId={versionId}
            localFindings={localFindings}
            localCapped={localCapped}
          />
        </div>
      )}
    </li>
  );
}

export function ValidationFindings({
  summary,
  versionId,
  localFindings,
  localCapped,
}: FindingsSource) {
  const [showInfo, setShowInfo] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { actionable, informational, counts } = useMemo(() => {
    const actionableRules = summary.filter((rule) => rule.severity !== 'info');
    const infoRules = summary.filter((rule) => rule.severity === 'info');
    const sum = (rules: RuleSummary[]) =>
      rules.reduce((total, rule) => total + rule.finding_count, 0);
    return {
      actionable: actionableRules,
      informational: infoRules,
      counts: {
        error: sum(summary.filter((r) => r.severity === 'error')),
        warning: sum(summary.filter((r) => r.severity === 'warning')),
        info: sum(infoRules),
        absent:
          infoRules.find((r) => r.rule_code === 'STRUCTURALLY_ABSENT')?.finding_count ?? 0,
      },
    };
  }, [summary]);

  const visible = showInfo ? [...actionable, ...informational] : actionable;

  return (
    <Card
      title="Validation findings"
      description="Grouped by rule. Expand a rule to see the offending value and the series it belongs to."
      actions={
        <div className="flex items-center gap-2">
          {counts.error > 0 && <SeverityChip severity="error" count={counts.error} />}
          {counts.warning > 0 && <SeverityChip severity="warning" count={counts.warning} />}
        </div>
      }
      bodyClassName="p-0"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface-alt px-card py-2.5">
        <p className="text-caption text-ink-muted">
          Showing <Figure>{formatCount(counts.error + counts.warning)}</Figure> errors and
          warnings.
          {counts.absent > 0 && (
            <>
              {' '}
              A further <Figure>{formatCount(counts.absent)}</Figure> findings record
              combinations that do not exist — a crop not grown or not priced in that
              district — rather than data that is missing.
            </>
          )}
        </p>
        {informational.length > 0 && (
          <label className="flex shrink-0 cursor-pointer items-center gap-2 text-body text-ink">
            <input
              type="checkbox"
              checked={showInfo}
              onChange={(event) => setShowInfo(event.target.checked)}
              className="h-4 w-4 rounded border-line-strong text-primary"
            />
            <span>
              Also show informational findings
              {counts.info > 0 && (
                <>
                  {' '}
                  <span className="text-ink-muted">
                    (<Figure>{formatCount(counts.info)}</Figure>)
                  </span>
                </>
              )}
            </span>
          </label>
        )}
      </div>

      {visible.length === 0 ? (
        <div className="p-card">
          <EmptyState
            title="No errors or warnings"
            detail={
              informational.length > 0
                ? 'Every finding for this dataset is informational. Use the toggle above to see them.'
                : 'This dataset produced no validation findings at all.'
            }
          />
        </div>
      ) : (
        <ul>
          {visible.map((rule) => (
            <RuleRow
              key={rule.rule_code}
              rule={rule}
              expanded={expanded === rule.rule_code}
              onToggle={() =>
                setExpanded((current) =>
                  current === rule.rule_code ? null : rule.rule_code,
                )
              }
              versionId={versionId}
              localFindings={localFindings}
              localCapped={localCapped}
            />
          ))}
        </ul>
      )}

      {showInfo && counts.absent > 0 && (
        <p className="border-t border-line bg-info-bg px-card py-2 text-caption text-ink-muted">
          <Badge tone="info">Structurally absent</Badge> findings are recorded as
          information, not as warnings: the series has no value in any year of any source,
          so the combination does not exist rather than being missing.
        </p>
      )}
    </Card>
  );
}
