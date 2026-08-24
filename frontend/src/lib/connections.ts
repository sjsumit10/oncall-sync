import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import type {
  ChatChannel,
  ChatConnection,
  ChatGroup,
  OncallConnection,
  OncallSchedule,
} from "./types";

/** The connections a rule can be built from. Shared by the builder and the identities page. */
export function useConnections() {
  const oncall = useQuery({
    queryKey: ["oncall-connections"],
    queryFn: () => api.get<OncallConnection[]>("/oncall/connections"),
  });
  const chat = useQuery({
    queryKey: ["chat-connections"],
    queryFn: () => api.get<ChatConnection[]>("/chat/connections"),
  });
  return {
    oncall: oncall.data ?? [],
    chat: chat.data ?? [],
    isPending: oncall.isPending || chat.isPending,
  };
}

export function useSchedules(connectionId: string | undefined) {
  return useQuery({
    queryKey: ["oncall-schedules", connectionId],
    queryFn: () => api.get<OncallSchedule[]>(`/oncall/connections/${connectionId}/schedules`),
    enabled: Boolean(connectionId),
  });
}

export function useGroups(connectionId: string | undefined) {
  return useQuery({
    queryKey: ["chat-groups", connectionId],
    queryFn: () => api.get<ChatGroup[]>(`/chat/connections/${connectionId}/groups`),
    enabled: Boolean(connectionId),
  });
}

export function useChannels(connectionId: string | undefined) {
  return useQuery({
    queryKey: ["chat-channels", connectionId],
    queryFn: () => api.get<ChatChannel[]>(`/chat/connections/${connectionId}/channels`),
    enabled: Boolean(connectionId),
  });
}
