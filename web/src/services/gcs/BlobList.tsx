import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./BlobList.module.css";

interface Props {
  api: UiApi;
}

export function BlobList({ api }: Props) {
  const { bucket = "" } = useParams<{ bucket: string }>();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const prefix = params.get("prefix") ?? "";
  const blobs = useAsync(
    () => api.listBlobs(bucket, { prefix, delimiter: "/" }),
    [bucket, prefix],
  );
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const goTo = (newPrefix: string) => {
    const next = new URLSearchParams(params);
    if (newPrefix) next.set("prefix", newPrefix);
    else next.delete("prefix");
    setParams(next);
  };

  const goUp = () => {
    if (!prefix) return;
    const trimmed = prefix.replace(/\/$/, "");
    const idx = trimmed.lastIndexOf("/");
    goTo(idx === -1 ? "" : trimmed.slice(0, idx + 1));
  };

  if (blobs.status === "loading" || blobs.status === "idle") {
    return <div>Loading…</div>;
  }
  if (blobs.status === "error") {
    return <ErrorBanner error={blobs.error!} onRetry={blobs.refresh} />;
  }

  const data = blobs.data!;
  const empty = data.blobs.length === 0 && data.folders.length === 0;

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBlob(bucket, pendingDelete);
    setPendingDelete(null);
    await blobs.refresh();
  };

  return (
    <div>
      <header className={styles.header}>
        <div>
          <button onClick={() => navigate("/gcs")} className={styles.back}>
            ← Buckets
          </button>
          <span className={styles.crumb}>
            {bucket}
            {prefix ? ` / ${prefix}` : ""}
          </span>
        </div>
      </header>
      {empty ? (
        <EmptyState
          title="This folder is empty"
          description="Upload a file to get started."
        />
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Size</th>
              <th>Content-Type</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {prefix && (
              <tr>
                <td colSpan={5}>
                  <button onClick={goUp} className={styles.link}>
                    ../
                  </button>
                </td>
              </tr>
            )}
            {data.folders.map((f) => (
              <tr key={f}>
                <td>
                  <button onClick={() => goTo(f)} className={styles.link}>
                    📁 {f.slice(prefix.length)}
                  </button>
                </td>
                <td colSpan={4}></td>
              </tr>
            ))}
            {data.blobs.map((b) => (
              <tr key={b.name}>
                <td>📄 {b.name.slice(prefix.length)}</td>
                <td>{b.size}</td>
                <td>{b.content_type}</td>
                <td>{b.updated}</td>
                <td>
                  <a href={api.downloadBlobUrl(bucket, b.name)} download>
                    Download
                  </a>{" "}
                  <button onClick={() => setPendingDelete(b.name)} className={styles.delete}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete "${pendingDelete}"?`}
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
