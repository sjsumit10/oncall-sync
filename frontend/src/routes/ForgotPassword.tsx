import { useState } from "react";

import { Field } from "@/components/field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useRequestPasswordReset } from "@/lib/auth";
import { AuthShell, errorMessage } from "./Login";

export default function ForgotPassword() {
  const request = useRequestPasswordReset();
  const [email, setEmail] = useState("");

  if (request.isSuccess) {
    return (
      <AuthShell title="Check your email" description="If that address has an account, a reset link is on its way.">
        <p className="text-sm text-muted-foreground">
          The link is valid for <span className="font-medium text-foreground">5 minutes</span>.
          Didn't get it? Check spam, or{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-4 hover:underline"
            onClick={() => request.reset()}
          >
            try again
          </button>
          .
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      description="Enter your email and we'll send you a link to reset it."
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          request.mutate({ email });
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
        {request.error && <Alert>{errorMessage(request.error)}</Alert>}
        <Button type="submit" className="w-full" size="lg" disabled={request.isPending}>
          {request.isPending ? "Sending…" : "Send reset link"}
        </Button>
      </form>
    </AuthShell>
  );
}
