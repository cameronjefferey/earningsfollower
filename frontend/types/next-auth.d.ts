import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    subscriptionStatus?: string;
    subscribed?: boolean;
    isAdmin?: boolean;
    /** AUTH_BYPASS_EMAILS — Pro without Stripe; not admin. */
    isVip?: boolean;
    /** True once when the backend just created this account (for ad pixels). */
    trackSignUp?: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    googleSub?: string;
    subscriptionStatus?: string;
    subscribed?: boolean;
    isAdmin?: boolean;
    isVip?: boolean;
    subscriptionCheckedAt?: number;
    picture?: string;
    trackSignUp?: boolean;
  }
}
