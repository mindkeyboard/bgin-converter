import { dialog } from "./dialogs";
import { t } from "./i18n";

import { TERMS_VERSION } from "./termsVersion";
export { TERMS_VERSION };
export const terms = [
  "Before Octane Loader is released, Binary GIN Editor may be used to replace BGIN files in the cache of any Gameloft game.",
  "Until OctaneLoader beta is released, use in large-scale modifications with modified classes is prohibited.",
  "After these releases, use in any project is permitted provided that its README credits the creator as mindkeyboard.",
  "The creator, mindkeyboard, is not responsible for misuse, harmful or unlawful uses, data loss, or consequences of changes made with this tool. Users are responsible for their actions and for respecting applicable laws and third-party rights.",
  "The editor is provided as is, without a guarantee of compatibility with every game. Keep backups of files before replacing them.",
  "On first opening a BGIN file, the dialog presents expandable terms. Only I agree to the terms saves acceptance in user settings.json. Closing does not accept; editing remains unavailable. Reopen the terms in Editor settings.",
  "After the first close or acceptance, the Octane Telegram channel opens once. Reopening the terms, another file or VS Code does not repeat the visit. Opening the channel does not subscribe you or replace accepting the terms.",
];

export function showTerms(accept?: () => void, dismissed?: () => void) {
  const modal = dialog(t("Terms of use"));
  modal.element.id = "termsDialog";
  if (dismissed) modal.element.addEventListener("close", dismissed, { once: true });
  const intro = document.createElement("p");
  intro.textContent = t("Read the terms before using Binary GIN Editor.");
  if (dismissed) {
    const channel = document.createElement("p");
    channel.textContent = t("After your first close or acceptance, the Octane Telegram channel will open once.");
    modal.body.append(channel);
  }
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = t("Terms of use") + " · " + TERMS_VERSION;
  details.append(summary);
  for (const text of terms) {
    const paragraph = document.createElement("p");
    paragraph.textContent = t(text);
    details.append(paragraph);
  }
  modal.body.append(intro, details);
  if (accept) {
    const button = document.createElement("button");
    button.id = "acceptTerms";
    button.className = "primary";
    button.textContent = t("I agree to the terms");
    button.onclick = () => { accept(); modal.element.close(); };
    modal.body.append(button);
  }
  modal.open();
}
