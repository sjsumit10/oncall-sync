/**
 * Mirrors the backend response models in app/api/v1/schemas.py.
 * `npm run gen:api` regenerates the full schema from the running API.
 */

export type UserRole = "owner" | "admin" | "member";

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
}

export interface Session {
  user: User;
  organization: Organization;
  csrf_token: string;
}

export interface Invite {
  id: string;
  email: string;
  role: UserRole;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

export interface InviteCreated {
  invite: Invite;
  accept_url: string;
}

export type ConnectionStatus = "active" | "needs_reauth" | "error";

export interface OncallProvider {
  kind: string;
  display_name: string;
  auth_modes: string[];
  supports_oauth: boolean;
  /** False when the deployment has no OAuth app registered for this provider. */
  oauth_configured: boolean;
}

export interface OncallConnection {
  id: string;
  kind: string;
  auth_mode: "oauth" | "api_key";
  display_name: string;
  status: ConnectionStatus;
  scopes: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  schedules_synced_at: string | null;
  created_at: string;
}

export interface OncallSchedule {
  id: string;
  connection_id: string;
  external_id: string;
  name: string;
  timezone: string;
  description: string | null;
  html_url: string | null;
  synced_at: string;
}

export interface ConnectionHealth {
  ok: boolean;
  detail: string;
}

export interface ChatProvider {
  kind: string;
  display_name: string;
  install_configured: boolean;
}

export interface ChatConnection {
  id: string;
  kind: string;
  external_team_id: string;
  team_name: string;
  status: ConnectionStatus;
  scopes: string | null;
  /** False when no installer token is held — no fallback if the workspace locks down user groups. */
  has_user_token: boolean;
  last_verified_at: string | null;
  last_error: string | null;
  groups_synced_at: string | null;
  created_at: string;
}

export interface ChatGroup {
  id: string;
  external_id: string;
  handle: string;
  name: string;
  is_active: boolean;
  synced_at: string;
}

export interface ChatChannel {
  id: string;
  external_id: string;
  name: string;
  is_private: boolean;
  bot_is_member: boolean;
  synced_at: string;
}

export type RuleStatus = "pending" | "healthy" | "degraded" | "failing";

export interface SyncRule {
  id: string;
  name: string;
  enabled: boolean;
  oncall_connection_id: string;
  schedule_external_id: string;
  escalation_levels: number[];
  chat_connection_id: string;
  group_external_id: string;
  fallback_chat_user_id: string | null;
  notify_channel_external_id: string | null;
  notify_on_change: boolean;
  message_template: string | null;
  status: RuleStatus;
  last_synced_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  created_at: string;
}

export interface ProviderUser {
  external_id: string;
  name: string;
  email: string | null;
}

export interface ResolvedMember {
  provider_user: ProviderUser;
  chat_user_id: string;
  chat_user_name: string | null;
  source: "auto_email" | "manual";
}

export interface RulePreview {
  evaluated_at: string;
  schedule_name: string;
  on_call: ProviderUser[];
  resolved: ResolvedMember[];
  unmapped: ProviderUser[];
  desired_member_ids: string[];
  current_member_ids: string[];
  /** False when the rule is degraded and the handle will be left alone. */
  would_write: boolean;
  would_add: string[];
  would_remove: string[];
  used_fallback: boolean;
  shift_start: string | null;
  next_change_at: string | null;
  problems: string[];
}

export interface IdentityLink {
  id: string;
  provider_user_id: string;
  provider_email: string | null;
  provider_name: string | null;
  chat_user_id: string;
  chat_user_name: string | null;
  source: "auto_email" | "manual";
  updated_at: string;
}

export interface DirectoryEntry {
  provider_user: ProviderUser;
  link: IdentityLink | null;
}

export interface SyncRun {
  id: string;
  rule_id: string;
  trigger: "scheduled" | "manual" | "event";
  status: "success" | "degraded" | "failed" | "skipped";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  previous_members: string[] | null;
  new_members: string[] | null;
  actions: string[] | null;
  problems: string[] | null;
  error: string | null;
}

export interface MessagePreview {
  text: string;
  blocks: Array<Record<string, unknown>>;
  problems: string[];
  /** The sample values the preview rendered with, for labelling each variable. */
  variables: Record<string, string>;
}

export interface ActivityRun extends SyncRun {
  rule_name: string;
}

export interface Overview {
  rules_total: number;
  rules_by_status: Record<string, number>;
  rules_paused: number;
  connections_needing_attention: number;
  /** The most recent run that actually changed who is on call. */
  last_handoff_at: string | null;
  last_run_at: string | null;
}
