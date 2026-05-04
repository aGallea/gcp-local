import { useState } from "react";
import { Link } from "react-router-dom";

import { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import { CreateBucketDialog } from "./CreateBucketDialog";
import styles from "./BucketList.module.css";

interface Props {
  api: UiApi;
}

export function BucketList({ api }: Props) {
  const buckets = useAsync(() => api.listBuckets(), []);
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<Error | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const handleCreate = async (payload: { name: string; location: string }) => {
    setCreateError(null);
    try {
      await api.createBucket(payload);
      setCreateOpen(false);
      await buckets.refresh();
    } catch (e) {
      setCreateError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBucket(pendingDelete);
    setPendingDelete(null);
    await buckets.refresh();
  };

  if (buckets.status === "loading" || buckets.status === "idle") {
    return <div>Loading…</div>;
  }
  if (buckets.status === "error") {
    return <ErrorBanner error={buckets.error!} onRetry={buckets.refresh} />;
  }
  const list = buckets.data!.buckets;
  if (list.length === 0) {
    return (
      <>
        <EmptyState
          title="No buckets yet"
          description="GCS is ready — create your first bucket to start storing objects."
          actionLabel="Create your first bucket"
          onAction={() => setCreateOpen(true)}
        />
        <CreateBucketDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onSubmit={handleCreate}
          error={createError}
        />
      </>
    );
  }

  return (
    <div>
      <header className={styles.header}>
        <h2>Buckets</h2>
        <button className={styles.create} onClick={() => setCreateOpen(true)}>
          Create bucket
        </button>
      </header>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Location</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.map((b) => (
            <tr key={b.name}>
              <td>
                <Link to={`/gcs/buckets/${encodeURIComponent(b.name)}`}>{b.name}</Link>
              </td>
              <td>{b.location}</td>
              <td>{b.time_created}</td>
              <td>
                <button onClick={() => setPendingDelete(b.name)} className={styles.delete}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CreateBucketDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={handleCreate}
        error={createError}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete bucket "${pendingDelete}"?`}
        message="This deletes the bucket. If it isn't empty the request will fail; rerun with force from the CLI if needed."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
