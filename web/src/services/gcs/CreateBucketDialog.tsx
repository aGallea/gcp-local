import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: { name: string; location: string }) => Promise<void>;
  error: Error | null;
}

const LOCATIONS = ["US", "EU", "ASIA"];

export function CreateBucketDialog({ open, onClose, onSubmit, error }: Props) {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("US");
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ name, location });
      setName("");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;
  return (
    <ConfirmDialog
      open
      title="Create bucket"
      message={
        <div>
          <label>
            Name <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <div style={{ marginTop: 12 }}>
            <label>
              Location{" "}
              <select value={location} onChange={(e) => setLocation(e.target.value)}>
                {LOCATIONS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
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
