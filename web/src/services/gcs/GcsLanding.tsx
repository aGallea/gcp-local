import { Route, Routes } from "react-router-dom";

import { api } from "../../api/client";

import { BlobList } from "./BlobList";
import { BucketList } from "./BucketList";

export default function GcsLanding() {
  return (
    <Routes>
      <Route index element={<BucketList api={api} />} />
      <Route path="buckets/:bucket/*" element={<BlobList api={api} />} />
    </Routes>
  );
}
