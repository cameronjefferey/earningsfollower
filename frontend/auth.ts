import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { SignJWT } from "jose";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

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

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
    }),
  ],
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async jwt({ token, account, profile, trigger }) {
      if (account && profile?.email) {
        token.email = profile.email;
        token.name = profile.name ?? token.name;
        token.picture = typeof profile.picture === "string" ? profile.picture : token.picture;
        token.googleSub = typeof profile.sub === "string" ? profile.sub : token.googleSub;
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
        trigger === "update" ||
        !token.subscriptionCheckedAt ||
        Date.now() - Number(token.subscriptionCheckedAt) > 5 * 60 * 1000;

      if (shouldSync && token.email) {
        const synced =
          (accessToken && (await fetchMe(accessToken))) ||
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
      return session;
    },
  },
});
