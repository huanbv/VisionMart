import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "@/components/AppLayout";
import AIAnalyticsPage from "@/pages/AIAnalyticsPage";
import AiTrainingPage from "@/pages/AiTrainingPage";
import AuditLogsPage from "@/pages/AuditLogsPage";
import BranchesPage from "@/pages/BranchesPage";
import CamerasPage from "@/pages/CamerasPage";
import CategoriesPage from "@/pages/CategoriesPage";
import CustomersPage from "@/pages/CustomersPage";
import DashboardPage from "@/pages/DashboardPage";
import DetectionsPage from "@/pages/DetectionsPage";
import EmployeesPage from "@/pages/EmployeesPage";
import InventoryPage from "@/pages/InventoryPage";
import LiveCartPage from "@/pages/LiveCartPage";
import LoginPage from "@/pages/LoginPage";
import NotificationsPage from "@/pages/NotificationsPage";
import OrdersPage from "@/pages/OrdersPage";
import OrganizationPage from "@/pages/OrganizationPage";
import PosPage from "@/pages/PosPage";
import ProductsPage from "@/pages/ProductsPage";
import ReportsPage from "@/pages/ReportsPage";
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
        <Route path="/categories" element={<CategoriesPage />} />
        <Route path="/products" element={<ProductsPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/pos" element={<PosPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/live-cart" element={<LiveCartPage />} />
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/employees" element={<EmployeesPage />} />
        <Route path="/cameras" element={<CamerasPage />} />
        <Route path="/detections" element={<DetectionsPage />} />
        <Route path="/ai-analytics" element={<AIAnalyticsPage />} />
        <Route path="/ai-training" element={<AiTrainingPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/roles" element={<RolesPage />} />
        <Route path="/audit-logs" element={<AuditLogsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

