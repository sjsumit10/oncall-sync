import { useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { Alert, Button, Field } from "@/components/ui";
import { useSession, useSignup } from "@/lib/auth";
import { AuthShell, errorMessage } from "./Login";

export default function Signup() {
  const { data: session } = useSession();
  const signup = useSignup();
  const [form, setForm] = useState({
    organization_name: "",
    name: "",
    email: "",
    password: "",
  });

  if (session) return <Navigate to="/" replace />;

  const update = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <AuthShell title="Create your organization">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          signup.mutate(form);
        }}
      >
        <Field
          label="Organization"
          required
          value={form.organization_name}
          onChange={update("organization_name")}
        />
        <Field label="Your name" required value={form.name} onChange={update("name")} />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update("email")}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          value={form.password}
          onChange={update("password")}
        />
        <p className="text-xs text-slate-500">At least 12 characters.</p>
        {signup.error && <Alert>{errorMessage(signup.error)}</Alert>}
        <Button type="submit" className="w-full" disabled={signup.isPending}>
          {signup.isPending ? "Creating…" : "Create organization"}
        </Button>
      </form>
      <p className="mt-4 text-sm text-slate-500">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-slate-900 underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
