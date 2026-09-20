import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/AppLayout";
import { RequireAuth } from "@/components/RequireAuth";
import AcceptInvite from "@/routes/AcceptInvite";
import Activity from "@/routes/Activity";
import Connections from "@/routes/Connections";
import ForgotPassword from "@/routes/ForgotPassword";
import Identities from "@/routes/Identities";
import Landing from "@/routes/Landing";
import Login from "@/routes/Login";
import Overview from "@/routes/Overview";
import Plans from "@/routes/Plans";
import ResetPassword from "@/routes/ResetPassword";
import RuleBuilder from "@/routes/RuleBuilder";
import Rules from "@/routes/Rules";
import Settings from "@/routes/Settings";
import Signup from "@/routes/Signup";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/overview" element={<Overview />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/rules/new" element={<RuleBuilder />} />
        <Route path="/rules/:ruleId/edit" element={<RuleBuilder />} />
        <Route path="/identities" element={<Identities />} />
        <Route path="/plans" element={<Plans />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
