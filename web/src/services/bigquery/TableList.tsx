import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./bigquery.module.css";

interface Props {
  api: UiApi;
}

export function TableList({ api }: Props) {
  const { project = "", dataset = "" } = useParams<{ project: string; dataset: string }>();
  const navigate = useNavigate();
  const tables = useAsync(() => api.listBqTables(project, dataset), [project, dataset]);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBqTable(project, dataset, pendingDelete);
    setPendingDelete(null);
    await tables.refresh();
  };

  if (tables.status === "loading" || tables.status === "idle") {
    return <div>Loading…</div>;
  }
  if (tables.status === "error") {
    return <ErrorBanner error={tables.error!} onRetry={tables.refresh} />;
  }

  const list = tables.data!.tables;

  const header = (
    <header className={styles.header}>
      <div>
        <button onClick={() => navigate("/bigquery")} className={styles.back}>
          ← Projects
        </button>
        <span className={styles.crumb}>
          <Link
            to={`/bigquery/projects/${encodeURIComponent(project)}`}
            className={styles.crumbLink}
          >
            {project}
          </Link>
          {" / "}
          {dataset}
        </span>
      </div>
      <div className={styles.actions}>
        <Link
          to={`/bigquery/projects/${encodeURIComponent(project)}/query`}
          className={styles.secondary}
        >
          Query console
        </Link>
      </div>
    </header>
  );

  if (list.length === 0) {
    return (
      <div>
        {header}
        <EmptyState
          title="No tables in this dataset"
          description="Create a table by loading data through the BigQuery REST API or running CREATE TABLE in the query console."
        />
      </div>
    );
  }

  return (
    <div>
      {header}
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Table</th>
            <th>Rows</th>
            <th>Created</th>
            <th>Last modified</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.map((t) => (
            <tr key={t.table_id}>
              <td>
                <Link
                  to={`/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(dataset)}/tables/${encodeURIComponent(t.table_id)}`}
                >
                  {t.table_id}
                </Link>
              </td>
              <td>{t.num_rows.toLocaleString()}</td>
              <td>{t.create_time}</td>
              <td>{t.last_modified_time}</td>
              <td>
                <button onClick={() => setPendingDelete(t.table_id)} className={styles.delete}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete table "${pendingDelete}"?`}
        message="Drops the table and its data."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
