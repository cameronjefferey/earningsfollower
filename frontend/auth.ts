import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { SignJWT } from "jose";
import { readAuthRequestContext } from "@/lib/auth-request-context";
import { isBotSuspect, scoreBot } from "@/lib/bot";

// Server-side jwt callbacks need an absolute API URL. Prefer AUTH_API_BASE so
// Render isn't dependent on NEXT_PUBLIC_* inlining for Auth.js.
const API_BASE =
  process.env.AUTH_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://127.0.0.1:8000";

async function mintAccessToken(claims: {
  sub?: string | null;
  email?: string | null;
  name?: string | null;
}): Promise<string | undefined> {
  const secret = process.env.AUTH_SECRET;
  if (!secret || !claims.email) return undefined;
  return new SignJWT({
    sub: claims.sub ?? undefined,
    email: claims.email,
    name: claims.name ?? undefined,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("30d")
    .sign(new TextEncoder().encode(secret));
}

async function syncUser(input: {
  email: string;
  name?: string | null;
  image?: string | null;
  googleSub?: string | null;
  accessToken?: string;
}): Promise<{
  subscriptionStatus: string;
  subscribed: boolean;
  isAdmin: boolean;
  created: boolean;
} | null> {
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (input.accessToken) {
      headers.Authorization = `Bearer ${input.accessToken}`;
    }
    const res = await fetch(`${API_BASE}/auth/upsert`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        email: input.email,
        name: input.name ?? null,
        image: input.image ?? null,
        google_sub: input.googleSub ?? null,
      }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      subscription_status: string;
      subscribed: boolean;
      is_admin?: boolean;
      created?: boolean;
    };
    return {
      subscriptionStatus: data.subscription_status,
      subscribed: data.subscribed,
      isAdmin: Boolean(data.is_admin),
      created: Boolean(data.created),
    };
  } catch {
    return null;
  }
}

async function fetchMe(accessToken: string): Promise<{
  subscriptionStatus: string;
  subscribed: boolean;
  isAdmin: boolean;
} | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      subscription_status: string;
      subscribed: boolean;
      is_admin?: boolean;
    };
    return {
      subscriptionStatus: data.subscription_status,
      subscribed: data.subscribed,
      isAdmin: Boolean(data.is_admin),
    };
  } catch {
    return null;
  }
}

/** Auth errors that block sign-in / signup (not routine session noise). */
const SIGNUP_AUTH_ALERT_TYPES = new Set([
  "InvalidCheck",
  "CallbackRouteError",
  "OAuthCallbackError",
  "OAuthSignInError",
  "CredentialsSignin",
  "AccessDenied",
  "Configuration",
  "AccountNotLinked",
  "OAuthAccountNotLinked",
  "MissingCSRF",
]);

function authErrorType(error: Error): string {
  const typed = error as Error & { type?: string };
  return typed.type || error.name || "Error";
}

function authErrorCause(error: Error): string | undefined {
  const withCause = error as Error & {
    cause?: unknown;
    [key: string]: unknown;
  };
  const cause = withCause.cause;
  if (!cause) return undefined;
  if (cause instanceof Error) {
    return `${cause.name}: ${cause.message}`.slice(0, 400);
  }
  if (typeof cause === "object" && cause && "err" in cause) {
    const inner = (cause as { err?: unknown }).err;
    if (inner instanceof Error) {
      return `${inner.name}: ${inner.message}`.slice(0, 400);
    }
    try {
      return JSON.stringify(inner).slice(0, 400);
    } catch {
      return String(inner).slice(0, 400);
    }
  }
  try {
    return JSON.stringify(cause).slice(0, 400);
  } catch {
    return String(cause).slice(0, 400);
  }
}

function reportAuthFailure(error: Error): void {
  const type = authErrorType(error);
  if (!SIGNUP_AUTH_ALERT_TYPES.has(type)) return;

  const secret = process.env.AUTH_SECRET;
  if (!secret) return;

  const ctx = readAuthRequestContext();
  const ua = ctx?.ua || "";
  const { score } = scoreBot(ua);
  const bot = isBotSuspect(score);
  const cause = authErrorCause(error);

  // Fire-and-forget; never block the Auth.js response path.
  void fetch(`${API_BASE}/ops/traffic`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${secret}`,
      ...(ua ? { "User-Agent": ua } : {}),
      ...(ctx?.ip ? { "X-Forwarded-For": ctx.ip } : {}),
    },
    body: JSON.stringify({
      kind: "auth_fail",
      path: ctx?.path,
      ua,
      auth_error: type,
      auth_cause: cause,
      message:
        `${bot ? "[BOT] " : ""}Auth fail: ${type}` +
        (cause ? ` · ${cause.slice(0, 180)}` : "") +
        (error.message && !cause ? ` — ${error.message.slice(0, 180)}` : ""),
    }),
    cache: "no-store",
  }).catch(() => {
    /* ignore — alerting must never break auth */
  });
}

async function authorizeCredentials(
  credentials: Partial<Record<"email" | "password" | "magicToken", unknown>>
): Promise<{ id: string; email: string; name?: string | null } | null> {
  const magicToken =
    typeof credentials.magicToken === "string" ? credentials.magicToken.trim() : "";
  if (magicToken) {
    const res = await fetch(`${API_BASE}/auth/magic/consume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: magicToken }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { email?: string; name?: string | null };
    if (!data.email) return null;
    return { id: data.email, email: data.email, name: data.name ?? null };
  }

  const email =
    typeof credentials.email === "string" ? credentials.email.trim().toLowerCase() : "";
  const password =
    typeof credentials.password === "string" ? credentials.password : "";
  if (!email || !password) return null;

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { email?: string; name?: string | null };
  if (!data.email) return null;
  return { id: data.email, email: data.email, name: data.name ?? null };
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
      // Backend users are keyed by email; allow Google to merge with password /
      // magic-link accounts that already use the same address.
      allowDangerousEmailAccountLinking: true,
    }),
    Credentials({
      id: "credentials",
      name: "Email",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
        magicToken: { label: "Magic token", type: "text" },
      },
      authorize: async (credentials) => authorizeCredentials(credentials ?? {}),
    }),
  ],
  pages: {
    signIn: "/login",
  },
  logger: {
    error(error) {
      const name = authErrorType(error);
      console.error(`[auth][error] ${name}: ${error.message}`);
      reportAuthFailure(error);
    },
  },
  callbacks: {
    async jwt({ token, user, account, profile, trigger }) {
      // Credentials / OAuth both pass a user on the first sign-in tick.
      if (user?.email) {
        token.email = user.email;
        token.name = user.name ?? token.name;
        if (typeof user.image === "string") {
          token.picture = user.image;
        }
      }

      if (account?.provider === "google" && profile?.email) {
        token.email = profile.email;
        token.name = profile.name ?? token.name;
        token.picture =
          typeof profile.picture === "string" ? profile.picture : token.picture;
        token.googleSub =
          typeof profile.sub === "string" ? profile.sub : token.googleSub;
      }

      const accessToken = await mintAccessToken({
        sub: (token.googleSub as string | undefined) ?? token.sub,
        email: token.email,
        name: token.name,
      });
      if (accessToken) {
        token.accessToken = accessToken;
      }

      const shouldSync =
        Boolean(account) ||
        Boolean(user) ||
        trigger === "update" ||
        !token.subscriptionCheckedAt ||
        Date.now() - Number(token.subscriptionCheckedAt) > 5 * 60 * 1000;

      if (shouldSync && token.email) {
        // Prefer upsert on the first OAuth/credentials tick so we learn `created`
        // (for Reddit SignUp). Later refreshes can use /auth/me.
        const firstTick = Boolean(account) || Boolean(user);
        const synced = firstTick
          ? await syncUser({
              email: String(token.email),
              name: token.name,
              image: typeof token.picture === "string" ? token.picture : null,
              googleSub: token.googleSub as string | undefined,
              accessToken,
            })
          : (accessToken && (await fetchMe(accessToken))) ||
            (await syncUser({
              email: String(token.email),
              name: token.name,
              image: typeof token.picture === "string" ? token.picture : null,
              googleSub: token.googleSub as string | undefined,
              accessToken,
            }));
        if (synced) {
          token.subscriptionStatus = synced.subscriptionStatus;
          token.subscribed = synced.subscribed;
          token.isAdmin = synced.isAdmin;
          token.subscriptionCheckedAt = Date.now();
          if ("created" in synced && synced.created) {
            token.trackSignUp = true;
          }
        }
      }

      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.email = token.email ?? session.user.email;
        session.user.name = token.name ?? session.user.name;
        if (typeof token.picture === "string") {
          session.user.image = token.picture;
        }
      }
      session.accessToken = token.accessToken as string | undefined;
      session.subscriptionStatus = (token.subscriptionStatus as string) ?? "none";
      session.subscribed = Boolean(token.subscribed);
      session.isAdmin = Boolean(token.isAdmin);
      session.trackSignUp = Boolean(token.trackSignUp);
      return session;
    },
  },
});
