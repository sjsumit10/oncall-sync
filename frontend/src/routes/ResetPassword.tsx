import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import { Field } from "@/components/field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useConfirmPasswordReset, useSession } from "@/lib/auth";
import { AuthShell, errorMessage } from "./Login";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { data: session } = useSession();
  const confirm = useConfirmPasswordReset();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  if (session && confirm.isSuccess) return <Navigate to="/overview" replace />;

  const mismatch = confirmPassword.length > 0 && password !== confirmPassword;

  return (
    <AuthShell title="Set a new password" description="Choose a new password for your account.">
      {!token ? (
        <Alert>
          This reset link is missing its token. Request a new one from the login page.
        </Alert>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (mismatch) return;
            confirm.mutate({ token, password });
          }}
        >
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Field
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            error={mismatch ? "Passwords don't match." : undefined}
          />
          <p className="text-xs text-muted-foreground">At least 12 characters.</p>
          {confirm.error && <Alert>{errorMessage(confirm.error)}</Alert>}
          <Button
            type="submit"
            className="w-full"
            size="lg"
            disabled={confirm.isPending || mismatch}
          >
            {confirm.isPending ? "Resetting…" : "Reset password"}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
