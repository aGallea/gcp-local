import type { UiApi } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./BlobPreview.module.css";

interface Props {
  api: UiApi;
  bucket: string;
  name: string;
  onClose: () => void;
}

export function BlobPreview({ api, bucket, name, onClose }: Props) {
  const meta = useAsync(() => api.getBlobMetadata(bucket, name), [bucket, name]);

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <header className={styles.header}>
          <h2>{name}</h2>
          <button onClick={onClose} aria-label="close">×</button>
        </header>
        <div className={styles.body}>
          {meta.status === "loading" || meta.status === "idle" ? (
            <div>Loading…</div>
          ) : meta.status === "error" ? (
            <ErrorBanner error={meta.error!} onRetry={meta.refresh} />
          ) : (
            <PreviewBody api={api} data={meta.data!} />
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewBody({
  api,
  data,
}: {
  api: UiApi;
  data: NonNullable<Awaited<ReturnType<UiApi["getBlobMetadata"]>>>;
}) {
  const downloadHref = api.downloadBlobUrl(data.bucket, data.name);
  const preview = data.preview;
  return (
    <>
      <dl className={styles.meta}>
        <dt>Size</dt>
        <dd>{data.size}</dd>
        <dt>Content-Type</dt>
        <dd>{data.content_type}</dd>
        <dt>Updated</dt>
        <dd>{data.updated}</dd>
      </dl>
      <a href={downloadHref} className={styles.download} download>
        Download
      </a>
      {preview?.kind === "text" || preview?.kind === "json" ? (
        <>
          {preview.truncated && (
            <div className={styles.truncated}>Preview truncated to first 1 MB.</div>
          )}
          <pre className={styles.text}>{preview.text}</pre>
        </>
      ) : preview?.kind === "image" && preview.image_data_url ? (
        <img src={preview.image_data_url} alt={data.name} className={styles.image} />
      ) : (
        <div className={styles.none}>{preview?.reason ?? "No inline preview."}</div>
      )}
    </>
  );
}
