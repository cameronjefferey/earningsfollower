import { AsyncLocalStorage } from "node:async_hooks";

export type AuthRequestContext = {
  ua: string;
  ip: string;
  path: string;
};

export const authRequestContext = new AsyncLocalStorage<AuthRequestContext>();

export function readAuthRequestContext(): AuthRequestContext | null {
  return authRequestContext.getStore() ?? null;
}
