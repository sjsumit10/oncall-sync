import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "./api";
import type { Session } from "./types";

const SESSION_KEY = ["session"];

/**
 * The single source of truth for "is anyone logged in".
 *
 * A 401 is a valid answer, not a failure — it resolves to null so the router can
 * redirect rather than showing an error state.
 */
export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async (): Promise<Session | null> => {
      try {
        return await api.get<Session>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.isUnauthenticated) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

function useSessionMutation<TInput>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TInput) => api.post<Session>(path, input),
    onSuccess: (session) => queryClient.setQueryData(SESSION_KEY, session),
  });
}

export interface SignupInput {
  name: string;
  email: string;
  password: string;
}

export const useSignup = () => useSessionMutation<SignupInput>("/auth/signup");
export const useLogin = () => useSessionMutation<{ email: string; password: string }>("/auth/login");
export const useAcceptInvite = () =>
  useSessionMutation<{ token: string; name: string; password: string }>("/auth/invites/accept");

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSuccess: () => {
      queryClient.setQueryData(SESSION_KEY, null);
      // Anything cached was scoped to the org that just logged out.
      queryClient.clear();
    },
  });
}
