import { useState } from "react";

import styles from "./BlobUploadDialog.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File) => Promise<void>;
}

export function BlobUploadDialog({ open, onClose, onUpload }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  if (!open) return null;

  const handleSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      await onUpload(file);
      setFile(null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2>Upload file</h2>
        <div
          className={`${styles.drop} ${dragActive ? styles.active : ""}`}
          onDragEnter={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            const f = e.dataTransfer.files?.[0];
            if (f) setFile(f);
          }}
        >
          {file ? (
            <div>
              {file.name} ({file.size} bytes)
            </div>
          ) : (
            <div>Drag a file here, or use the picker below.</div>
          )}
        </div>
        <label className={styles.picker}>
          Select file
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {error && <div className={styles.error}>{error.message}</div>}
        <div className={styles.actions}>
          <button onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!file || submitting}
            className={styles.confirm}
          >
            {submitting ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
