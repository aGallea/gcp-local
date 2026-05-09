import { Route, Routes } from "react-router-dom";

import { api } from "../../api/client";

import { DatasetList } from "./DatasetList";
import { ProjectList } from "./ProjectList";
import { QueryConsole } from "./QueryConsole";
import { TableDetail } from "./TableDetail";
import { TableList } from "./TableList";

export default function BigQueryLanding() {
  return (
    <Routes>
      <Route index element={<ProjectList api={api} />} />
      <Route path="projects/:project/query" element={<QueryConsole api={api} />} />
      <Route path="projects/:project" element={<DatasetList api={api} />} />
      <Route
        path="projects/:project/datasets/:dataset/tables/:table"
        element={<TableDetail api={api} />}
      />
      <Route
        path="projects/:project/datasets/:dataset"
        element={<TableList api={api} />}
      />
    </Routes>
  );
}
