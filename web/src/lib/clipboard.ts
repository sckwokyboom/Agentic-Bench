/**
 * Copy text to the clipboard, working in BOTH secure (HTTPS / localhost) and
 * plain-HTTP LAN contexts. `navigator.clipboard` is undefined over http:// on a
 * non-localhost host — exactly the `--expose` case — so we fall back to the
 * legacy execCommand + hidden-textarea trick. Returns whether the copy landed;
 * callers can still rely on the source text being selectable when this is false.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* secure-context copy blocked — fall through to the legacy path */
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
