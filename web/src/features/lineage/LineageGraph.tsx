/**
 * Lineage graph, drawn as plain SVG.
 *
 * The layout is computed, not simulated: a node's column comes from what kind
 * of node it is, and its row from alphabetical order within that column. The
 * same edges therefore always produce the same picture, which matters when a
 * reviewer sees the screen twice.
 *
 * SVG rather than a graph library because the graphs here are a handful of
 * nodes, and a force layout would move between run-throughs.
 */
import { useMemo } from 'react';

import type { LineageEdge } from '@/api/client';
import { cn } from '@/components/primitives';

const NODE_WIDTH = 188;
const NODE_HEIGHT = 46;
const COLUMN_GAP = 64;
const ROW_GAP = 16;
const PADDING = 12;

/** Stage a node belongs to. Order here is the left-to-right order on screen. */
const STAGES = [
  'Source file',
  'Raw',
  'Staging',
  'Analytics',
  'Derived view',
  'Export',
] as const;
type Stage = (typeof STAGES)[number];

function stageOf(node: string): Stage {
  if (node.startsWith('file:') || node.startsWith('upload:')) return 'Source file';
  if (node.startsWith('raw.')) return 'Raw';
  if (node.startsWith('staging.')) return 'Staging';
  if (node.startsWith('export:')) return 'Export';
  if (node.startsWith('analytics.v_')) return 'Derived view';
  return 'Analytics';
}

function label(node: string): { title: string; subtitle: string } {
  if (node.startsWith('file:')) return { title: node.slice(5), subtitle: 'source file' };
  if (node.startsWith('upload:')) return { title: node.slice(7), subtitle: 'upload' };
  if (node.startsWith('export:')) return { title: node.slice(7), subtitle: 'export' };
  const dot = node.indexOf('.');
  if (dot === -1) return { title: node, subtitle: '' };
  return { title: node.slice(dot + 1), subtitle: node.slice(0, dot) };
}

const EDGE_LABEL: Record<string, string> = {
  extract: 'extract',
  transform: 'transform',
  load: 'load',
  publish: 'publish',
  aggregate: 'aggregate',
  reference: 'reference',
  validate: 'validate',
};

interface PositionedNode {
  id: string;
  stage: Stage;
  x: number;
  y: number;
}

export function LineageGraph({
  edges,
  selectedNode,
  onSelectNode,
}: {
  edges: LineageEdge[];
  selectedNode: string | null;
  onSelectNode: (node: string) => void;
}) {
  const { nodes, width, height, columns } = useMemo(() => {
    const ids = new Set<string>();
    for (const edge of edges) {
      ids.add(edge.from_node);
      ids.add(edge.to_node);
    }

    const byStage = new Map<Stage, string[]>();
    for (const id of Array.from(ids).sort()) {
      const stage = stageOf(id);
      const bucket = byStage.get(stage) ?? [];
      bucket.push(id);
      byStage.set(stage, bucket);
    }

    // Keep only the stages actually present, preserving the declared order.
    const usedStages = STAGES.filter((stage) => byStage.has(stage));
    const positioned = new Map<string, PositionedNode>();
    let tallest = 0;

    usedStages.forEach((stage, columnIndex) => {
      const bucket = byStage.get(stage) ?? [];
      bucket.forEach((id, rowIndex) => {
        positioned.set(id, {
          id,
          stage,
          x: PADDING + columnIndex * (NODE_WIDTH + COLUMN_GAP),
          y: PADDING + 22 + rowIndex * (NODE_HEIGHT + ROW_GAP),
        });
      });
      tallest = Math.max(tallest, bucket.length);
    });

    return {
      nodes: positioned,
      columns: usedStages,
      width: PADDING * 2 + usedStages.length * NODE_WIDTH + (usedStages.length - 1) * COLUMN_GAP,
      height: PADDING * 2 + 22 + tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP,
    };
  }, [edges]);

  if (edges.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Lineage from source file through the storage layers to analytics and exports"
        className="min-w-full"
      >
        <defs>
          <marker
            id="lineage-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" className="fill-line-strong" />
          </marker>
        </defs>

        {columns.map((stage, index) => (
          <text
            key={stage}
            x={PADDING + index * (NODE_WIDTH + COLUMN_GAP)}
            y={PADDING + 8}
            className="fill-ink-subtle text-caption font-medium uppercase tracking-header"
          >
            {stage}
          </text>
        ))}

        {edges.map((edge, index) => {
          const from = nodes.get(edge.from_node);
          const to = nodes.get(edge.to_node);
          if (!from || !to) return null;
          const x1 = from.x + NODE_WIDTH;
          const y1 = from.y + NODE_HEIGHT / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_HEIGHT / 2;
          const midX = (x1 + x2) / 2;
          const highlighted =
            selectedNode === edge.from_node || selectedNode === edge.to_node;
          return (
            <g key={`${edge.from_node}->${edge.to_node}-${index}`}>
              <path
                d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                fill="none"
                strokeWidth={highlighted ? 2 : 1.25}
                className={highlighted ? 'stroke-primary' : 'stroke-line-strong'}
                markerEnd="url(#lineage-arrow)"
              />
              <text
                x={midX}
                y={(y1 + y2) / 2 - 5}
                textAnchor="middle"
                className={cn(
                  'text-caption',
                  highlighted ? 'fill-primary' : 'fill-ink-subtle',
                )}
              >
                {EDGE_LABEL[edge.edge_type] ?? edge.edge_type}
              </text>
            </g>
          );
        })}

        {Array.from(nodes.values()).map((node) => {
          const { title, subtitle } = label(node.id);
          const selected = selectedNode === node.id;
          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              tabIndex={0}
              role="button"
              aria-label={`${title}${subtitle ? `, ${subtitle}` : ''}`}
              onClick={() => onSelectNode(node.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelectNode(node.id);
                }
              }}
              className="cursor-pointer"
            >
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={4}
                className={cn(
                  'transition-colors duration-state',
                  selected
                    ? 'fill-primary-subtle stroke-primary'
                    : 'fill-surface stroke-line-strong',
                )}
                strokeWidth={selected ? 2 : 1}
              />
              <text
                x={10}
                y={19}
                className={cn(
                  'text-caption font-medium',
                  selected ? 'fill-primary' : 'fill-ink',
                )}
              >
                {title.length > 24 ? `${title.slice(0, 23)}…` : title}
              </text>
              <text x={10} y={34} className="fill-ink-subtle text-caption">
                {subtitle}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
