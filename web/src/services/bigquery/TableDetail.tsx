import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import { RowsTable } from "./RowsTable";
import { SchemaTree } from "./SchemaTree";
import styles from "./bigquery.module.css";

interface Props {
  api: UiApi;
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const DEFAULT_PAGE_SIZE = 20;

export function TableDetail({ api }: Props) {
  const {
    project = "",
    dataset = "",
    table = "",
  } = useParams<{ project: string; dataset: string; table: string }>();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const meta = useAsync(
    () => api.getBqTable(project, dataset, table),
    [project, dataset, table],
  );
  const preview = useAsync(
    () => api.previewBqTable(project, dataset, table, { maxResults: pageSize, offset }),
    [project, dataset, table, offset, pageSize],
  );

  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = preview.data
    ? Math.max(1, Math.ceil(preview.data.total_rows / pageSize))
    : 1;

  if (meta.status === "loading" || meta.status === "idle") {
    return <div>Loading…</div>;
  }
  if (meta.status === "error") {
    return <ErrorBanner error={meta.error!} onRetry={meta.refresh} />;
  }
  const data = meta.data!;

  return (
    <div>
      <header className={styles.header}>
        <div>
          <button onClick={() => navigate(-1)} className={styles.back}>
            ← Back
          </button>
          <span className={styles.crumb}>
            <Link
              to={`/bigquery/projects/${encodeURIComponent(project)}`}
              className={styles.crumbLink}
            >
              {project}
            </Link>
            {" / "}
            <Link
              to={`/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(dataset)}`}
              className={styles.crumbLink}
            >
              {dataset}
            </Link>
            {" / "}
            {table}
          </span>
        </div>
      </header>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h3>Details</h3>
          <span className={styles.rowCount}>{data.num_rows.toLocaleString()} rows</span>
        </div>
        <table className={styles.compactTable}>
          <tbody>
            <tr>
              <th>Rows</th>
              <td>{data.num_rows.toLocaleString()}</td>
            </tr>
            <tr>
              <th>Created</th>
              <td>{data.create_time}</td>
            </tr>
            <tr>
              <th>Last modified</th>
              <td>{data.last_modified_time}</td>
            </tr>
            {data.description && (
              <tr>
                <th>Description</th>
                <td>{data.description}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.section}>
        <h3>Schema</h3>
        <SchemaTree schema={data.table_schema} />
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h3>Preview</h3>
          {preview.status === "success" && (
            <span className={styles.rowCount}>
              {preview.data!.total_rows.toLocaleString()} total rows
            </span>
          )}
        </div>
        {preview.status === "loading" || preview.status === "idle" ? (
          <div>Loading rows…</div>
        ) : preview.status === "error" ? (
          <ErrorBanner error={preview.error!} onRetry={preview.refresh} />
        ) : (
          <>
            <RowsTable schema={preview.data!.table_schema} rows={preview.data!.rows} />
            <div className={styles.actions} style={{ marginTop: 12 }}>
              <button
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                disabled={offset === 0}
                className={styles.secondary}
              >
                Previous
              </button>
              <button
                onClick={() =>
                  preview.data!.next_offset !== null &&
                  setOffset(preview.data!.next_offset!)
                }
                disabled={preview.data!.next_offset === null}
                className={styles.secondary}
              >
                Next
              </button>
              <span className={styles.note}>
                Page {currentPage} of {totalPages} — rows {offset + 1}–
                {offset + preview.data!.rows.length} of{" "}
                {preview.data!.total_rows.toLocaleString()}
              </span>
              <label className={styles.pageSize} style={{ marginLeft: "auto" }}>
                Rows per page
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setOffset(0);
                  }}
                >
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
