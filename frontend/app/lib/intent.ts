export function intentClassName(level?: string | null) {
  if (!level) return "intent-unknown";
  if (level.includes("高")) return "intent-high";
  if (level.includes("中")) return "intent-mid";
  if (level.includes("低")) return "intent-low";
  if (level.includes("成交")) return "intent-done";
  if (level.includes("暂不")) return "intent-stop";
  return "intent-unknown";
}
