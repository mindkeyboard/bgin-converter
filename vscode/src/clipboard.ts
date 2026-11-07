/** Read one copied branch without dropping surrounding objects or changing its values. */
export function parseClipboardObject(raw: string): any {
  if (raw.length > 16 * 1024 * 1024)
    throw Error("Clipboard object is too large");

  let source = raw.trim();
  const fence = /^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```$/i.exec(source);
  if (fence) source = fence[1].trim();
  // A selection from a JSON array can include the separator after the object.
  if (source.endsWith(",")) source = source.slice(0, -1).trimEnd();

  let value: any;
  try {
    value = JSON.parse(source);
  } catch {
    try {
      // Selecting an object's fields can omit its outer braces. The entire
      // selection must parse; never extract just the first matching object.
      if (!source.startsWith('"')) throw Error();
      value = JSON.parse("{" + source + "}");
    } catch {
      throw Error("Clipboard is not valid JSON. Copy one complete BGIN object, including its braces.");
    }
  }
  if (Array.isArray(value)) {
    if (value.length !== 1)
      throw Error("Paste one BGIN object at a time. The clipboard contains a list of objects.");
    value = value[0];
  }
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("Clipboard must contain a valid BGIN object JSON");
  return value;
}
