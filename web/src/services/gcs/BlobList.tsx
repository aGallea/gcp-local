import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import { BlobPreview } from "./BlobPreview";
import { BlobUploadDialog } from "./BlobUploadDialog";
import { CreateFolderDialog } from "./CreateFolderDialog";
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
  const [pendingFolderDelete, setPendingFolderDelete] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [previewName, setPreviewName] = useState<string | null>(null);
  const [createFolderOpen, setCreateFolderOpen] = useState(false);
  const [createFolderError, setCreateFolderError] = useState<Error | null>(null);

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

  const handleUpload = async (file: File) => {
    await api.uploadBlob(bucket, file, prefix + file.name);
    await blobs.refresh();
  };

  const handleCreateFolder = async (folderName: string) => {
    setCreateFolderError(null);
    try {
      const trimmed = folderName.replace(/\/+$/, "");
      const placeholder = new File([new Uint8Array(0)], "", {
        type: "application/x-directory",
      });
      await api.uploadBlob(bucket, placeholder, prefix + trimmed + "/");
      setCreateFolderOpen(false);
      await blobs.refresh();
    } catch (e) {
      setCreateFolderError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  if (blobs.status === "loading" || blobs.status === "idle") {
    return <div>Loading…</div>;
  }
  if (blobs.status === "error") {
    return <ErrorBanner error={blobs.error!} onRetry={blobs.refresh} />;
  }

  const data = blobs.data!;
  const visibleBlobs = data.blobs.filter((b) => b.name !== prefix);
  const empty = visibleBlobs.length === 0 && data.folders.length === 0;

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await api.deleteBlob(bucket, pendingDelete);
    setPendingDelete(null);
    await blobs.refresh();
  };

  const confirmFolderDelete = async () => {
    if (!pendingFolderDelete) return;
    // Best-effort: delete the placeholder object. If the folder appears only
    // because of nested files (no placeholder), this 404s and we just refresh
    // so the user sees the folder is still there — they need to delete the
    // contained files first.
    try {
      await api.deleteBlob(bucket, pendingFolderDelete);
    } catch {
      // ignore — refresh will reveal whether anything changed.
    }
    setPendingFolderDelete(null);
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
            {prefix ? (
              <button onClick={() => goTo("")} className={styles.crumbLink}>
                {bucket}
              </button>
            ) : (
              bucket
            )}
            {prefix &&
              prefix
                .replace(/\/$/, "")
                .split("/")
                .filter(Boolean)
                .map((segment, idx, arr) => {
                  const isLast = idx === arr.length - 1;
                  const accum = arr.slice(0, idx + 1).join("/") + "/";
                  return (
                    <span key={accum}>
                      {" / "}
                      {isLast ? (
                        `${segment}/`
                      ) : (
                        <button
                          onClick={() => goTo(accum)}
                          className={styles.crumbLink}
                        >
                          {segment}/
                        </button>
                      )}
                    </span>
                  );
                })}
          </span>
        </div>
        <div className={styles.actions}>
          <button onClick={() => setCreateFolderOpen(true)} className={styles.secondary}>
            Create folder
          </button>
          <button onClick={() => setUploadOpen(true)} className={styles.upload}>
            Upload
          </button>
        </div>
      </header>
      {empty ? (
        <EmptyState
          title="This folder is empty"
          description="Upload a file or create a folder."
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
                <td colSpan={3}></td>
                <td>
                  <button
                    onClick={() => setPendingFolderDelete(f)}
                    className={styles.delete}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {visibleBlobs.map((b) => (
              <tr key={b.name}>
                <td>
                  <button onClick={() => setPreviewName(b.name)} className={styles.link}>
                    📄 {b.name.slice(prefix.length)}
                  </button>
                </td>
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
      <ConfirmDialog
        open={pendingFolderDelete !== null}
        title={`Delete folder "${pendingFolderDelete}"?`}
        message="Removes the folder placeholder. Files inside the folder are not deleted; if any remain, the folder will keep showing in the listing until you delete them too."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmFolderDelete}
        onCancel={() => setPendingFolderDelete(null)}
      />
      <BlobUploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUpload={handleUpload}
      />
      <CreateFolderDialog
        open={createFolderOpen}
        onClose={() => setCreateFolderOpen(false)}
        onSubmit={handleCreateFolder}
        error={createFolderError}
      />
      {previewName && (
        <BlobPreview
          api={api}
          bucket={bucket}
          name={previewName}
          onClose={() => setPreviewName(null)}
        />
      )}
    </div>
  );
}
