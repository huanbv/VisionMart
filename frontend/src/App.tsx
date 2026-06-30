import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "@/components/AppLayout";
import BranchesPage from "@/pages/BranchesPage";
import DashboardPage from "@/pages/DashboardPage";
import LoginPage from "@/pages/LoginPage";
import OrganizationPage from "@/pages/OrganizationPage";
import RolesPage from "@/pages/RolesPage";
import UsersPage from "@/pages/UsersPage";
import { RequireAuth } from "@/routes/RequireAuth";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/organization" element={<OrganizationPage />} />
        <Route path="/branches" element={<BranchesPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/roles" element={<RolesPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

