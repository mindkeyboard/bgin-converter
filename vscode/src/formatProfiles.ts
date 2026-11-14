/** Binary encodings are separate from resource compression and preview coverage. */
export const formatProfiles = [
  { id: "a8-0.0.2", label: "~0.0.2" },
  { id: "a8-1.6.0", label: "~1.6.0" },
  { id: "a8-3.7.0", label: "~3.7.0" },
  { id: "a8-5.8.0", label: "~5.8.0" },
] as const;

export function normalizeFormat(value: unknown): string | undefined {
  if (value === "legacy") return "a8-0.0.2";
  if (value === "hashed") return "a8-1.6.0";
  if (typeof value === "string" && formatProfiles.some((profile) => profile.id === "a8-" + value)) return "a8-" + value;
  return formatProfiles.some((profile) => profile.id === value) ? String(value) : undefined;
}

export function documentFormat(text: string): string | undefined {
  try {
    const document = JSON.parse(text);
    if (!document?.name) return undefined;
    return normalizeFormat(document.format ?? "a8-1.6.0");
  } catch { return undefined; }
}

export function formatLabel(value: unknown): string {
  return formatProfiles.find((profile) => profile.id === normalizeFormat(value))?.label || "Unknown format";
}
