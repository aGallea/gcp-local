import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, type UiApi } from "../../api/client";
import type { BqQueryResult } from "../../api/types";

import { RowsTable } from "./RowsTable";
import styles from "./bigquery.module.css";

interface Props {
  api: UiApi;
}

const DEFAULT_SQL = "-- Try a query, e.g.\n-- SELECT 1 AS one, 'hello' AS greeting\n";

export function QueryConsole({ api }: Props) {
  const { project = "" } = useParams<{ project: string }>();
  const navigate = useNavigate();
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<BqQueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setRequestError(null);
    try {
      const r = await api.runBqQuery({ project, sql, max_results: 200 });
      setResult(r);
    } catch (e) {
      setResult(null);
      setRequestError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <header className={styles.header}>
        <div>
          <button onClick={() => navigate(-1)} className={styles.back}>
            ← Back
          </button>
          <span className={styles.crumb}>
            <Link
              to={`/bigquery/projects/${encodeURIComponent(project)}`}
              className={styles.crumbLink}
            >
              {project}
            </Link>
            {" / query"}
          </span>
        </div>
      </header>

      <textarea
        className={styles.queryBox}
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        spellCheck={false}
      />
      <div className={styles.actions} style={{ marginTop: 12 }}>
        <button onClick={run} disabled={running} className={styles.primary}>
          {running ? "Running…" : "Run"}
        </button>
        <span className={styles.note}>
          Queries run synchronously and read from project <code>{project}</code>. Use
          <code> `project.dataset.table` </code>
          to reference tables.
        </span>
      </div>

      {requestError && <div className={styles.error}>{requestError}</div>}
      {result?.error && <div className={styles.error}>{result.error}</div>}

      {result && !result.error && (
        <div className={styles.section}>
          <h3>
            Results
            <span className={styles.tag}>{result.statement_type}</span>
            <span className={styles.tag}>{result.total_rows} rows</span>
          </h3>
          {result.statement_type === "SELECT" ? (
            <RowsTable schema={result.table_schema} rows={result.rows} />
          ) : (
            <div className={styles.note}>Statement executed.</div>
          )}
        </div>
      )}
    </div>
  );
}
