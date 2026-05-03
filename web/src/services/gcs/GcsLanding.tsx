import { Route, Routes } from "react-router-dom";

import { api } from "../../api/client";

import { BucketList } from "./BucketList";

export default function GcsLanding() {
  return (
    <Routes>
      <Route index element={<BucketList api={api} />} />
      <Route path="buckets/:bucket/*" element={<div>Bucket detail (next task)</div>} />
    </Routes>
  );
}
