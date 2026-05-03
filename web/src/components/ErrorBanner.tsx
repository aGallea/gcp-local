import type { ApiError } from "../api/client";

import styles from "./ErrorBanner.module.css";

interface Props {
  error: ApiError | Error;
  onRetry?: () => void;
}

export function ErrorBanner({ error, onRetry }: Props) {
  return (
    <div role="alert" className={styles.banner}>
      <div className={styles.message}>{error.message}</div>
      {onRetry && (
        <button className={styles.retry} onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
