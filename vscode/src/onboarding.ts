import type { Memento } from "vscode";

export const CHANNEL_URL = "https://t.me/octaneloader";
export const CHANNEL_VISIT_KEY = "bgin.firstTermsChannelVisited";

/** Keep the first terms interaction independent of acceptance and window count. */
export class FirstRunChannel {
  private attempted = false;
  constructor(private state: Memento, public openChannel: () => Thenable<boolean>) {}

  async complete() {
    if (this.attempted || this.state.get<boolean>(CHANNEL_VISIT_KEY, false)) return;
    // Claim synchronously so simultaneous editor panels cannot open two tabs.
    this.attempted = true;
    await this.state.update(CHANNEL_VISIT_KEY, true);
    await this.openChannel();
  }
}
