import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import { CreateDatasetDialog } from "./CreateDatasetDialog";
import styles from "./bigquery.module.css";

interface Props {
  api: UiApi;
}

export function DatasetList({ api }: Props) {
  const { project = "" } = useParams<{ project: string }>();
  const navigate = useNavigate();
  const datasets = useAsync(() => api.listBqDatasets(project), [project]);
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<Error | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<Error | null>(null);

  const handleCreate = async (payload: { dataset_id: string; location: string }) => {
    setCreateError(null);
    try {
      await api.createBqDataset(project, payload);
      setCreateOpen(false);
      await datasets.refresh();
    } catch (e) {
      setCreateError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleteError(null);
    try {
      await api.deleteBqDataset(project, pendingDelete);
      setPendingDelete(null);
      await datasets.refresh();
    } catch (e) {
      setDeleteError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  if (datasets.status === "loading" || datasets.status === "idle") {
    return <div>Loading…</div>;
  }
  if (datasets.status === "error") {
    return <ErrorBanner error={datasets.error!} onRetry={datasets.refresh} />;
  }

  const list = datasets.data!.datasets;

  const header = (
    <header className={styles.header}>
      <div>
        <button onClick={() => navigate("/bigquery")} className={styles.back}>
          ← Projects
        </button>
        <span className={styles.crumb}>{project}</span>
      </div>
      <div className={styles.actions}>
        <Link
          to={`/bigquery/projects/${encodeURIComponent(project)}/query`}
          className={styles.secondary}
        >
          Query console
        </Link>
        <button onClick={() => setCreateOpen(true)} className={styles.primary}>
          Create dataset
        </button>
      </div>
    </header>
  );

  if (list.length === 0) {
    return (
      <div>
        {header}
        <EmptyState
          title="No datasets yet"
          description={`Create your first dataset in project "${project}".`}
          actionLabel="Create dataset"
          onAction={() => setCreateOpen(true)}
        />
        <CreateDatasetDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onSubmit={handleCreate}
          error={createError}
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
            <th>Dataset</th>
            <th>Location</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.map((d) => (
            <tr key={d.dataset_id}>
              <td>
                <Link
                  to={`/bigquery/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(d.dataset_id)}`}
                >
                  {d.dataset_id}
                </Link>
              </td>
              <td>{d.location}</td>
              <td>{d.create_time}</td>
              <td>
                <button onClick={() => setPendingDelete(d.dataset_id)} className={styles.delete}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CreateDatasetDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={handleCreate}
        error={createError}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete dataset "${pendingDelete}"?`}
        message={
          <div>
            <p>
              Deletes the dataset. If it isn't empty the request fails; drop tables first
              or use the CLI with delete_contents=true.
            </p>
            {deleteError && (
              <div style={{ color: "var(--danger)" }}>{deleteError.message}</div>
            )}
          </div>
        }
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteError(null);
        }}
      />
    </div>
  );
}
