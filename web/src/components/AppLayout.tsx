import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import type { ServiceInfo } from "../api/types";

import styles from "./AppLayout.module.css";

const SERVICE_LABELS: Record<string, string> = {
  gcs: "GCS",
  bigquery: "BigQuery",
  secret_manager: "Secret Manager",
  pubsub: "Pub/Sub",
  firestore: "Firestore",
};

export interface AppLayoutProps {
  services: ServiceInfo[];
  host: string;
  version?: string;
  children: ReactNode;
}

export function AppLayout({ services, host, version, children }: AppLayoutProps) {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          gcp-local
          {version && <span className={styles.versionTag}>v{version}</span>}
        </div>
        <div className={styles.section}>Services</div>
        <ul className={styles.nav}>
          {services.map((s) => {
            const label = SERVICE_LABELS[s.name] ?? s.name;
            if (!s.ui_supported) {
              return (
                <li key={s.name} className={styles.disabled} title="UI coming soon">
                  {label}
                </li>
              );
            }
            return (
              <li key={s.name}>
                <NavLink
                  to={`/${s.name}`}
                  className={({ isActive }) => (isActive ? styles.active : "")}
                >
                  {label}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </aside>
      <main className={styles.main}>
        <div className={styles.topbar}>
          <span className={styles.host}>{host}</span>
        </div>
        <div className={styles.content}>{children}</div>
      </main>
    </div>
  );
}
