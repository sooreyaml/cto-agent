import { logger } from "./logger.js";

export function dispatchDetached(label: string, work: () => Promise<void>): void {
  void work().catch((err) => {
    logger.error({ err, label }, "background task failed");
  });
}
