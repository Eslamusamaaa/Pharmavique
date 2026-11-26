// Saved assistant conversations (ADR-022): the signed-in person's list, and shared copies anyone
// with the link can read.
import { API_URL, ApiError, type AssistantAnswer, type Level } from '@/api/client';
import { authed } from '@/api/me';

export type ConversationSummary = {
  id: string;
  title: string;
  level: Level;
  pinned: boolean;
  questions: number;
  created_at: string;
  updated_at: string;
  shared: boolean;
  share_token: string | null;
};

export type ConversationList = {
  level: Level;
  conversations: ConversationSummary[];
  total: number;
  limit: number;
  warn_at: number;
  max_pinned: number;
};

export type SavedMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  status: 'ok' | 'pending' | 'failed';
  created_at: string;
  answer: AssistantAnswer | null; // an answer as it was shown, with its citations
};

export type ConversationDetail = { conversation: ConversationSummary; messages: SavedMessage[]; disclaimer: string };

export type SharedConversation = {
  title: string;
  level: Level;
  shared_at: string;
  messages: SavedMessage[];
  disclaimer: string;
};

const BASE = '/v1/assistant/conversations';

export function listConversations(q?: string, level?: Level, signal?: AbortSignal): Promise<ConversationList> {
  const params = new URLSearchParams();
  if (q?.trim()) params.set('q', q.trim());
  if (level) params.set('level', level);
  const query = params.toString();
  return authed<ConversationList>('GET', query ? `${BASE}?${query}` : BASE, undefined, signal);
}

export const getConversation = (id: string, signal?: AbortSignal) =>
  authed<ConversationDetail>('GET', `${BASE}/${id}`, undefined, signal);

export const renameConversation = (id: string, title: string) =>
  authed<ConversationSummary>('PATCH', `${BASE}/${id}`, { title });

export const pinConversation = (id: string, pinned: boolean) =>
  authed<ConversationSummary>('PATCH', `${BASE}/${id}`, { pinned });

export const deleteConversation = (id: string) => authed<void>('DELETE', `${BASE}/${id}`);

export const deleteAllConversations = (level?: Level) =>
  authed<{ deleted: number }>('DELETE', level ? `${BASE}?level=${level}` : BASE);

/** After the first answer: the model names the conversation (the question stays as its title if it cannot). */
export const writeTitle = (id: string) => authed<ConversationSummary>('POST', `${BASE}/${id}/title`);

export const shareConversation = (id: string) => authed<{ token: string; path: string }>('POST', `${BASE}/${id}/share`);

export const unshareConversation = (id: string) => authed<void>('DELETE', `${BASE}/${id}/share`);

/** The full link to a shared conversation, on the address the app was opened from. */
export function shareLink(path: string): string {
  const origin = typeof window !== 'undefined' && window.location ? window.location.origin : API_URL;
  return `${origin}${path}`;
}

/** A shared copy: public, no account needed. */
export async function getShared(token: string, signal?: AbortSignal): Promise<SharedConversation> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/shared/${encodeURIComponent(token)}`, {
      signal,
      headers: { Accept: 'application/json' },
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError('network', null, error instanceof Error ? error.message.slice(0, 160) : '');
  }
  if (!response.ok) throw new ApiError(`http ${response.status}`, response.status);
  return (await response.json()) as SharedConversation;
}
