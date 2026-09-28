import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { ApiError } from "./api/client";
import { AuthProvider, RequireAuth, ToastProvider } from "./components/shell";
import Login from "./pages/Login";
import Patients from "./pages/Patients";
import PatientLayout from "./pages/PatientLayout";
import Overview from "./pages/Overview";
import SystemPage from "./pages/System";
import Parameter from "./pages/Parameter";
import Medications from "./pages/Medications";
import Documents from "./pages/Documents";
import SummaryPage from "./pages/Summary";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (n, e) => !(e instanceof ApiError && [401, 404].includes(e.status)) && n < 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ToastProvider>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/patients" element={<RequireAuth><Patients /></RequireAuth>} />
              <Route path="/patients/:code" element={<RequireAuth><PatientLayout /></RequireAuth>}>
                <Route index element={<Overview />} />
                <Route path="systems/:system" element={<SystemPage />} />
                <Route path="parameters/:analyte" element={<Parameter />} />
                <Route path="medications" element={<Medications />} />
                <Route path="documents" element={<Documents />} />
                <Route path="summary" element={<SummaryPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/patients" replace />} />
            </Routes>
          </AuthProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
