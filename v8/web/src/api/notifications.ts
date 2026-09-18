import { api } from './client';
export interface AttentionRequest { request: string; url: string }
export interface Attention { participant: string; cursor: number; requests: AttentionRequest[] }
export const attention = (since = -1, request?: string): Promise<Attention> => api<Attention>(
  `/v1/me/notifications?${request ? `request=${encodeURIComponent(request)}` : `since=${since}`}`,
);
