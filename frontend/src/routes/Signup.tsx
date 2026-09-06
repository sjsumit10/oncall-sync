import { useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { Field } from "@/components/field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useSession, useSignup } from "@/lib/auth";
import { AuthShell, errorMessage } from "./Login";

export default function Signup() {
  const { data: session } = useSession();
  const signup = useSignup();
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
  });

  if (session) return <Navigate to="/overview" replace />;

  const update = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <AuthShell title="Create your account" description="Get your team synced in under a minute.">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          signup.mutate(form);
        }}
      >
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
        <p className="text-xs text-muted-foreground">At least 12 characters.</p>
        {signup.error && <Alert>{errorMessage(signup.error)}</Alert>}
        <Button type="submit" className="w-full" size="lg" disabled={signup.isPending}>
          {signup.isPending ? "Signing up…" : "Sign Up"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
