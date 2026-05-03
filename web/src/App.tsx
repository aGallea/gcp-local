import { Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { AppLayout } from "./components/AppLayout";
import { ErrorBanner } from "./components/ErrorBanner";
import { useAsync } from "./hooks/useAsync";
import GcsLanding from "./services/gcs/GcsLanding";

export default function App() {
  const services = useAsync(() => api.listServices(), []);

  if (services.status === "loading" || services.status === "idle") {
    return <div style={{ padding: 24 }}>Loading…</div>;
  }
  if (services.status === "error") {
    return <ErrorBanner error={services.error!} onRetry={services.refresh} />;
  }
  const list = services.data!.services;
  return (
    <AppLayout services={list} host={window.location.host}>
      <Routes>
        <Route path="/" element={<Navigate to="/gcs" replace />} />
        <Route path="/gcs/*" element={<GcsLanding />} />
      </Routes>
    </AppLayout>
  );
}
