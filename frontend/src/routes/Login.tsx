import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";

import { Alert, Button, Card, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLogin, useSession } from "@/lib/auth";

export default function Login() {
  const { data: session } = useSession();
  const login = useLogin();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (session) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  return (
    <AuthShell title="Sign in">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          login.mutate({ email, password });
        }}
      >
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {login.error && <Alert>{errorMessage(login.error)}</Alert>}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-4 text-sm text-slate-500">
        No account?{" "}
        <Link to="/signup" className="font-medium text-slate-900 underline">
          Create one
        </Link>
      </p>
    </AuthShell>
  );
}

export function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-lg font-semibold text-slate-900">{title}</h1>
        <Card>{children}</Card>
      </div>
    </div>
  );
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}
