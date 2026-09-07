// ============================================================
// UtiliVault Field — Design System v2.0
// Professional, field-friendly dark theme with refined palette.
// Optimized for outdoor use: high contrast, large touch targets.
// ============================================================

export const colors = {
  // Backgrounds
  bg: "#0f172a",
  bgDark: "#0b1120",
  bgElevated: "#1e293b",

  // Surfaces
  surface: "#1e293b",
  surfaceLight: "#334155",
  surfaceHover: "#3d4f66",

  // Borders
  border: "#475569",
  borderLight: "#64748b",
  borderFocus: "#f59e0b",

  // Text
  text: "#f1f5f9",
  textDim: "#94a3b8",
  textMuted: "#64748b",

  // Accents
  accent: "#f59e0b",        // amber gold
  accentLight: "#fbbf24",   // lighter amber
  accentDark: "#d97706",    // darker amber

  // Theme colors (water/utility)
  water: "#06b6d4",       // cyan
  waterDark: "#0891b2",
  waterLight: "#22d3ee",

  // Status
  success: "#10b981",
  error: "#f43f5e",
  warning: "#f59e0b",
  info: "#3b82f6",

  // Input
  inputBg: "#0b1220",
  inputBorder: "#334155",
};

// ── Typography ──────────────────────────────────────────────
export const typography = {
  h1: { fontSize: 28, fontWeight: "800", color: colors.text, letterSpacing: -0.5 },
  h2: { fontSize: 22, fontWeight: "700", color: colors.text, letterSpacing: -0.3 },
  h3: { fontSize: 18, fontWeight: "700", color: colors.text },
  body: { fontSize: 16, fontWeight: "400", color: colors.text, lineHeight: 22 },
  bodySmall: { fontSize: 14, fontWeight: "400", color: colors.textDim, lineHeight: 20 },
  caption: { fontSize: 12, fontWeight: "500", color: colors.textMuted, letterSpacing: 0.3 },
  label: { fontSize: 13, fontWeight: "600", color: colors.textDim, letterSpacing: 0.5, textTransform: "uppercase" },
  button: { fontSize: 16, fontWeight: "700", color: "#0f172a", letterSpacing: 0.3 },
};

// ── Shadows ─────────────────────────────────────────────────
export const shadows = {
  sm: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 2,
    elevation: 2,
  },
  md: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 4,
  },
  lg: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  glowAccent: {
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 6,
  },
  glowWater: {
    shadowColor: colors.water,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 4,
  },
};

// ── Base component styles ───────────────────────────────────
export const card = {
  backgroundColor: colors.surface,
  borderRadius: 14,
  padding: 16,
  borderWidth: 1,
  borderColor: colors.border,
  ...shadows.md,
};

export const input = {
  backgroundColor: colors.inputBg,
  borderColor: colors.inputBorder,
  borderWidth: 1.5,
  borderRadius: 10,
  color: colors.text,
  paddingHorizontal: 14,
  paddingVertical: 12,
  fontSize: 16,
  ...typography.body,
};

export const labelStyle = {
  ...typography.label,
  marginBottom: 6,
  marginTop: 12,
};

// ── Buttons ─────────────────────────────────────────────────
export const btn = (bg, hasShadow = true) => ({
  backgroundColor: bg,
  borderRadius: 12,
  paddingVertical: 14,
  paddingHorizontal: 20,
  alignItems: "center",
  justifyContent: "center",
  flexDirection: "row",
  gap: 8,
  ...(hasShadow ? shadows.md : {}),
});

export const btnText = (fg = "#0f172a") => ({
  ...typography.button,
  color: fg,
});

export const btnOutline = (borderColor, textColor) => ({
  backgroundColor: "transparent",
  borderRadius: 12,
  borderWidth: 1.5,
  borderColor: borderColor,
  paddingVertical: 14,
  paddingHorizontal: 20,
  alignItems: "center",
  justifyContent: "center",
  flexDirection: "row",
  gap: 8,
});

// ── Spacing ─────────────────────────────────────────────────
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 28,
};

// ── Status badge colors ─────────────────────────────────────
export const statusColors = {
  online: { bg: "#064e3b", text: colors.success, border: "#059669" },
  offline: { bg: "#450a0a", text: colors.error, border: "#dc2626" },
  warning: { bg: "#451a03", text: colors.warning, border: "#d97706" },
  info: { bg: "#172554", text: colors.info, border: "#2563eb" },
};
