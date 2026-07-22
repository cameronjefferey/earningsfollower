import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    subscriptionStatus?: string;
    subscribed?: boolean;
    isAdmin?: boolean;
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
  }
}
