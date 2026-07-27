/**
 * Shared utilities
 */

const COMMIT_TYPES = ["feat", "fix", "docs", "style", "refactor", "test", "chore", "other"];

const TYPE_COLORS = {
  feat: "success",
  fix: "danger",
  docs: "info",
  style: "",
  refactor: "warning",
  test: "success",
  chore: "info",
  other: "info",
};

function truncate(text, n = 50) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n) + "…" : text;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  }
}

function formatNow() {
  const d = new Date();
  return d.toLocaleTimeString();
}

function debounce(fn, wait = 300) {
  let t = null;
  return function debounced(...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), wait);
  };
}

window.GitIntegratorUtils = {
  COMMIT_TYPES,
  TYPE_COLORS,
  truncate,
  copyText,
  formatNow,
  debounce,
};
