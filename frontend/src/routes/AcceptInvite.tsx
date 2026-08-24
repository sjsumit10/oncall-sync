import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { Alert, Button, Field } from "@/components/ui";
import { useAcceptInvite, useSession } from "@/lib/auth";
import { AuthShell, errorMessage } from "./Login";

export default function AcceptInvite() {
  const { token = "" } = useParams();
  const { data: session } = useSession();
  const accept = useAcceptInvite();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  // Landing here already signed in means the invite is for a different person.
  if (session && accept.isSuccess) return <Navigate to="/" replace />;

  return (
    <AuthShell title="Join the team">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          accept.mutate({ token, name, password });
        }}
      >
        <Field
          label="Your name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="text-xs text-slate-500">At least 12 characters.</p>
        {accept.error && <Alert>{errorMessage(accept.error)}</Alert>}
        <Button type="submit" className="w-full" disabled={accept.isPending}>
          {accept.isPending ? "Joining…" : "Accept invite"}
        </Button>
      </form>
    </AuthShell>
  );
}
