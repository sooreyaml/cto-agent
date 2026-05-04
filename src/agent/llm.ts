import OpenAI from "openai";
import { config } from "../config.js";

export const llm = new OpenAI({
  baseURL: config.OPENROUTER_BASE_URL,
  apiKey: config.OPENROUTER_API_KEY,
  defaultHeaders: {
    "HTTP-Referer": config.APP_PUBLIC_URL,
    "X-Title": "CTO Agent",
  },
});

export const MODEL = config.OPENROUTER_MODEL;
