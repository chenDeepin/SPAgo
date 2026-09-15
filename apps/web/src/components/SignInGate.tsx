import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";

interface SignInGateProps {
  children: React.ReactNode;
}

/** Sign-in gate for hosted deployments (ONLINE-03/04).
 *
 * In local single-user mode this renders its children and nothing else: the
 * local product must keep working with no accounts (ADR-0002). In hosted mode it
 * holds the app behind a session and shows the states the plan requires —
 * invitation required, expired/invalid token, revoked session — instead of a
 * blank page or a broken workspace. */
export function SignInGate({ children }: SignInGateProps) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["auth-status"],
    queryFn: ({ signal }) => api.authStatus(signal),
    staleTime: 30_000,
  });

  // An invitation link lands on `/?invite=<token>`: pre-fill it so the invitee
  // does not have to copy it out of the URL by hand.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("invite");
    if (fromUrl) setToken(fromUrl);
  }, []);

  const redeem = useMutation({
    mutationFn: (value: string) => api.redeemInvitation(value),
    onSuccess: () => {
      setError(null);
      // Drop the token from the URL once it has been redeemed: it is single-use,
      // and leaving it in the address bar invites a copy/paste leak.
      const params = new URLSearchParams(window.location.search);
      if (params.has("invite")) {
        params.delete("invite");
        const qs = params.toString();
        window.history.replaceState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
      }
      queryClient.invalidateQueries();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Sign-in failed."),
  });

  const signOut = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      queryClient.clear();
      queryClient.invalidateQueries({ queryKey: ["auth-status"] });
    },
  });

  const status = statusQuery.data;

  if (!status || status.required === false) {
    return <>{children}</>;
  }

  if (!status.authenticated) {
    return (
      <div className="signin-shell">
        <div className="signin-card">
          <h1>SPAgo</h1>
          <p className="scope-note">
            This deployment is invitation-only. Sign-in uses the invitation link an operator sent
            you; there is no self-service signup and no password.
          </p>
          {status.note && <p className="fineprint">{status.note}</p>}
          <label className="input-label" htmlFor="invite-token">
            Invitation token
          </label>
          <input
            id="invite-token"
            className="text-input"
            type="text"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              setError(null);
            }}
            placeholder="Paste your invitation token or open the link you were sent"
            autoComplete="off"
          />
          {error && (
            <div className="state-banner error" role="alert">
              <span>{error}</span>
            </div>
          )}
          <button
            className="btn btn-primary"
            disabled={token.trim().length < 8 || redeem.isPending}
            onClick={() => redeem.mutate(token.trim())}
          >
            {redeem.isPending ? "Signing in…" : "Sign in"}
          </button>
          <p className="fineprint">
            Invitations are single-use and expire. If yours has expired or was revoked, ask the
            operator for a new one. Session cookies are HttpOnly; this page never stores your
            token.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="session-banner" role="status">
        <span>
          Signed in as <strong>{status.email}</strong>
          {status.is_admin ? " (administrator)" : ""} · private workspace
        </span>
        <span className="spacer" />
        <button className="show-all-occ" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
          {signOut.isPending ? "Signing out…" : "Sign out"}
        </button>
      </div>
      {children}
    </>
  );
}
