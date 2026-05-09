import { useState } from "react";

import type { BqCell, BqFieldInfo } from "../../api/types";

import styles from "./bigquery.module.css";

interface Props {
  schema: BqFieldInfo[];
  rows: BqCell[][];
}

interface ExpandedCell {
  field: string;
  value: BqCell;
}

export function RowsTable({ schema, rows }: Props) {
  const [expanded, setExpanded] = useState<ExpandedCell | null>(null);

  if (rows.length === 0) {
    return <div className={styles.note}>No rows.</div>;
  }
  return (
    <>
      <div className={styles.scroll}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              {schema.map((f) => (
                <th key={f.name}>
                  {f.name}
                  <span className={styles.tag}>{f.type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>
                    <CellView
                      value={cell}
                      onExpand={() =>
                        setExpanded({ field: schema[j]?.name ?? `col${j}`, value: cell })
                      }
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {expanded && (
        <CellModal cell={expanded} onClose={() => setExpanded(null)} />
      )}
    </>
  );
}

function CellView({ value, onExpand }: { value: BqCell; onExpand: () => void }) {
  if (value === null) {
    return <span className={styles.cellNull}>null</span>;
  }
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  const isLong = text.length > 80 || text.includes("\n");
  if (!isLong && (typeof value === "string" || typeof value === "number" || typeof value === "boolean")) {
    return <>{String(value)}</>;
  }
  return (
    <button
      type="button"
      className={styles.cellExpand}
      onClick={onExpand}
      title="Click to view full value"
    >
      <span className={typeof value === "object" ? styles.cellComplex : ""}>
        <span className={styles.cellClip}>{text}</span>
      </span>
    </button>
  );
}

function CellModal({ cell, onClose }: { cell: ExpandedCell; onClose: () => void }) {
  const text =
    cell.value === null
      ? "null"
      : typeof cell.value === "object"
        ? JSON.stringify(cell.value, null, 2)
        : String(cell.value);
  return (
    <div
      className={styles.cellModalBackdrop}
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div className={styles.cellModal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.cellModalHeader}>
          <h3>{cell.field}</h3>
          <button onClick={onClose} aria-label="close" className={styles.link}>
            ×
          </button>
        </div>
        <div className={styles.cellModalBody}>{text}</div>
      </div>
    </div>
  );
}
