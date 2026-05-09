import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { UiApi } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAsync } from "../../hooks/useAsync";

import styles from "./bigquery.module.css";

interface Props {
  api: UiApi;
}

export function ProjectList({ api }: Props) {
  const projects = useAsync(() => api.listBqProjects(), []);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerProject, setPickerProject] = useState("my-project");
  const navigate = useNavigate();

  if (projects.status === "loading" || projects.status === "idle") {
    return <div>Loading…</div>;
  }
  if (projects.status === "error") {
    return <ErrorBanner error={projects.error!} onRetry={projects.refresh} />;
  }
  const list = projects.data!.projects;

  const openProject = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setPickerOpen(false);
    navigate(`/bigquery/projects/${encodeURIComponent(trimmed)}`);
  };

  if (list.length === 0) {
    return (
      <>
        <EmptyState
          title="No BigQuery projects yet"
          description="BigQuery is ready — open a project to create your first dataset."
          actionLabel="Open project"
          onAction={() => setPickerOpen(true)}
        />
        <ConfirmDialog
          open={pickerOpen}
          title="Open project"
          message={
            <div>
              <label>
                Project ID{" "}
                <input
                  value={pickerProject}
                  onChange={(e) => setPickerProject(e.target.value)}
                  autoFocus
                />
              </label>
              <div className={styles.note}>
                BigQuery resources are scoped to a project. Datasets are created lazily —
                pick any ID and you can start adding datasets.
              </div>
            </div>
          }
          confirmLabel="Open"
          onConfirm={() => openProject(pickerProject)}
          onCancel={() => setPickerOpen(false)}
        />
      </>
    );
  }

  return (
    <div>
      <header className={styles.header}>
        <h2>BigQuery projects</h2>
        <button className={styles.primary} onClick={() => setPickerOpen(true)}>
          Open project
        </button>
      </header>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Project</th>
            <th>Datasets</th>
          </tr>
        </thead>
        <tbody>
          {list.map((p) => (
            <tr key={p.project}>
              <td>
                <Link to={`/bigquery/projects/${encodeURIComponent(p.project)}`}>
                  {p.project}
                </Link>
              </td>
              <td>{p.dataset_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ConfirmDialog
        open={pickerOpen}
        title="Open project"
        message={
          <div>
            <label>
              Project ID{" "}
              <input
                value={pickerProject}
                onChange={(e) => setPickerProject(e.target.value)}
                autoFocus
              />
            </label>
          </div>
        }
        confirmLabel="Open"
        onConfirm={() => openProject(pickerProject)}
        onCancel={() => setPickerOpen(false)}
      />
    </div>
  );
}
