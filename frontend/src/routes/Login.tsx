import { Workflow } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { Field } from "@/components/field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
    <AuthShell title="Welcome back" description="Sign in to keep your on-call rotations in sync.">
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
        <Button type="submit" className="w-full" size="lg" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        No account?{" "}
        <Link to="/signup" className="font-medium text-primary underline-offset-4 hover:underline">
          Create one
        </Link>
      </p>
    </AuthShell>
  );
}

export function AuthShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <div className="flex flex-1 flex-col justify-center px-6 py-12 sm:px-10">
        <div className="mx-auto w-full max-w-sm">
          <Link to="/" className="mb-8 flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Workflow className="size-4.5" />
            </div>
            <span className="text-sm font-semibold tracking-tight text-foreground">
              On-Call Sync
            </span>
          </Link>

          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
          {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}

          <Card className="mt-8 border-border/70 shadow-sm">
            <CardContent className="pt-6">{children}</CardContent>
          </Card>
        </div>
      </div>

      <div className="relative hidden flex-1 items-center justify-center overflow-hidden bg-[hsl(var(--sidebar))] lg:flex">
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, hsl(var(--primary) / 0.35), transparent 45%), radial-gradient(circle at 80% 70%, hsl(var(--primary) / 0.25), transparent 40%)",
          }}
        />
        <div className="relative max-w-md px-10 text-center">
          <p className="text-2xl font-semibold leading-snug text-white">
            &ldquo;Whoever is on call is always one mention away.&rdquo;
          </p>
          <p className="mt-4 text-sm text-white/60">
            On-Call Sync keeps your chat user groups mapped to the right on-call schedule,
            automatically, so a handoff never leaves anyone in the dark.
          </p>
        </div>
      </div>
    </div>
  );
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}
