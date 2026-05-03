import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
  error: Error | null;
}

export function CreateFolderDialog({ open, onClose, onSubmit, error }: Props) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(name.trim());
      setName("");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;
  return (
    <ConfirmDialog
      open
      title="Create folder"
      message={
        <div>
          <label>
            Name <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <div style={{ marginTop: 8, color: "var(--muted)", fontSize: 12 }}>
            GCS folders are object-name prefixes; this creates an empty placeholder
            object named <code>{name || "<name>"}/</code>.
          </div>
          {error && <div style={{ color: "var(--danger)", marginTop: 12 }}>{error.message}</div>}
        </div>
      }
      confirmLabel={submitting ? "Creating…" : "Create"}
      onConfirm={handleConfirm}
      onCancel={onClose}
    />
  );
}
