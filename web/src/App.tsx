import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";

export default function App() {
  // Real services list comes from a useServices() hook in Task 21; the scaffold
  // hard-codes GCS so the shell renders during early development.
  const services = [
    { name: "gcs", ports: [{ number: 4443, protocol: "rest" }], ui_supported: true },
  ];
  return (
    <AppLayout services={services} host={window.location.host}>
      <Routes>
        <Route path="/" element={<Navigate to="/gcs" replace />} />
        <Route path="/gcs/*" element={<div>GCS placeholder</div>} />
      </Routes>
    </AppLayout>
  );
}
