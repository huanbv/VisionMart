import { Navigate, Route, Routes } from "react-router-dom";

import DashboardPage from "@/pages/DashboardPage";
import LoginPage from "@/pages/LoginPage";
import { RequireAuth } from "@/routes/RequireAuth";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

