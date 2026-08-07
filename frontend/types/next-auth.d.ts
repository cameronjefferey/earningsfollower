import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    subscriptionStatus?: string;
    subscribed?: boolean;
    isAdmin?: boolean;
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
    subscriptionCheckedAt?: number;
    picture?: string;
    trackSignUp?: boolean;
  }
}
