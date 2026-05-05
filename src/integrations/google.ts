import { google } from "googleapis";
import { config } from "../config.js";

type OAuth2Client = InstanceType<typeof google.auth.OAuth2>;

let cached: OAuth2Client | null = null;

export function getGoogleOAuth(): OAuth2Client {
  if (!config.GOOGLE_CLIENT_ID || !config.GOOGLE_CLIENT_SECRET || !config.GOOGLE_REFRESH_TOKEN) {
    throw new Error(
      "Google OAuth not configured (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN)"
    );
  }
  if (!cached) {
    const oauth2 = new google.auth.OAuth2(
      config.GOOGLE_CLIENT_ID,
      config.GOOGLE_CLIENT_SECRET,
      "https://developers.google.com/oauthplayground"
    );
    oauth2.setCredentials({ refresh_token: config.GOOGLE_REFRESH_TOKEN });
    cached = oauth2;
  }
  return cached;
}

export function getGmail() {
  return google.gmail({ version: "v1", auth: getGoogleOAuth() });
}

export function getCalendar() {
  return google.calendar({ version: "v3", auth: getGoogleOAuth() });
}
