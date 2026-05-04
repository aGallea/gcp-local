import type { ReactNode } from "react";

import styles from "./ConfirmDialog.module.css";

interface Props {
  open: boolean;
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  destructive?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  destructive = false,
}: Props) {
  if (!open) return null;
  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2 className={styles.title}>{title}</h2>
        {message && <div className={styles.body}>{message}</div>}
        <div className={styles.actions}>
          <button onClick={onCancel} className={styles.cancel}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={destructive ? styles.destructive : styles.confirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
