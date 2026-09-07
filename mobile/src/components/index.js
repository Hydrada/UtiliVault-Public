// ============================================================
// UtiliVault Field — Reusable UI Components
// Professional, accessible, field-friendly building blocks.
// ============================================================

import React from "react";
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { btn, btnOutline, btnText, card, colors, shadows, spacing, statusColors, typography } from "../theme";

// ── Button ──────────────────────────────────────────────────
export function Button({
  title,
  onPress,
  variant = "primary",   // primary | secondary | outline | ghost | danger
  size = "md",           // sm | md | lg
  icon,
  loading = false,
  disabled = false,
  style,
  textStyle,
}) {
  const variants = {
    primary: { bg: colors.accent, text: "#0f172a", outline: false },
    secondary: { bg: colors.water, text: "#ffffff", outline: false },
    outline: { bg: "transparent", text: colors.accent, outline: true, border: colors.accent },
    ghost: { bg: "transparent", text: colors.textDim, outline: false },
    danger: { bg: colors.error, text: "#ffffff", outline: false },
  };
  const v = variants[variant] || variants.primary;

  const sizes = {
    sm: { py: 10, px: 14, fs: 14 },
    md: { py: 14, px: 20, fs: 16 },
    lg: { py: 16, px: 24, fs: 17 },
  };
  const sz = sizes[size] || sizes.md;

  const baseStyle = v.outline
    ? btnOutline(v.border, v.text)
    : btn(v.bg, variant !== "ghost");

  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled || loading}
      activeOpacity={0.8}
      style={[
        baseStyle,
        {
          paddingVertical: sz.py,
          paddingHorizontal: sz.px,
          opacity: disabled ? 0.45 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={v.text} size="small" />
      ) : (
        <>
          {icon}
          <Text style={[btnText(v.text), { fontSize: sz.fs }, textStyle]}>{title}</Text>
        </>
      )}
    </TouchableOpacity>
  );
}

// ── Card ────────────────────────────────────────────────────
export function Card({ children, style, onPress }) {
  const Wrapper = onPress ? TouchableOpacity : View;
  return (
    <Wrapper
      onPress={onPress}
      activeOpacity={onPress ? 0.85 : 1}
      style={[styles.card, style]}
    >
      {children}
    </Wrapper>
  );
}

// ── Section ─────────────────────────────────────────────────
export function Section({ title, icon, children, style }) {
  return (
    <Card style={[styles.section, style]}>
      <View style={styles.sectionHeader}>
        {icon && <Text style={styles.sectionIcon}>{icon}</Text>}
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      {children}
    </Card>
  );
}

// ── StatusBadge ─────────────────────────────────────────────
export function StatusBadge({ status, label }) {
  const sc = statusColors[status] || statusColors.info;
  return (
    <View style={[styles.badge, { backgroundColor: sc.bg, borderColor: sc.border }]}>
      <View style={[styles.badgeDot, { backgroundColor: sc.text }]} />
      <Text style={[styles.badgeText, { color: sc.text }]}>{label}</Text>
    </View>
  );
}

// ── EmptyState ──────────────────────────────────────────────
export function EmptyState({ icon, title, subtitle }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyIcon}>{icon || "📋"}</Text>
      <Text style={styles.emptyTitle}>{title}</Text>
      {subtitle && <Text style={styles.emptySubtitle}>{subtitle}</Text>}
    </View>
  );
}

// ── Divider ─────────────────────────────────────────────────
export function Divider({ style }) {
  return <View style={[styles.divider, style]} />;
}

// ── Chip ────────────────────────────────────────────────────
export function Chip({ label, active, onPress, color }) {
  const bg = active ? (color || colors.accent) : colors.inputBg;
  const fg = active ? "#0f172a" : colors.textDim;
  const border = active ? (color || colors.accent) : colors.border;

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.8}
      style={[styles.chip, { backgroundColor: bg, borderColor: border }]}
    >
      <Text style={[styles.chipText, { color: fg }]}>{label}</Text>
    </TouchableOpacity>
  );
}

// ── ProgressDots ────────────────────────────────────────────
export function ProgressDots({ total, current, color = colors.accent }) {
  return (
    <View style={styles.dots}>
      {Array.from({ length: total }).map((_, i) => (
        <View
          key={i}
          style={[
            styles.dot,
            i === current && { backgroundColor: color, width: 20 },
          ]}
        />
      ))}
    </View>
  );
}

// ── Styles ──────────────────────────────────────────────────
const styles = StyleSheet.create({
  card: {
    ...card,
  },
  section: {
    marginBottom: spacing.lg,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  sectionIcon: {
    fontSize: 18,
  },
  sectionTitle: {
    ...typography.label,
    color: colors.accent,
    marginTop: 0,
    marginBottom: 0,
  },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 20,
    borderWidth: 1,
    alignSelf: "flex-start",
  },
  badgeDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: "700",
  },
  empty: {
    alignItems: "center",
    paddingVertical: 40,
    paddingHorizontal: 20,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: spacing.md,
    opacity: 0.6,
  },
  emptyTitle: {
    ...typography.h3,
    color: colors.textDim,
    textAlign: "center",
  },
  emptySubtitle: {
    ...typography.bodySmall,
    color: colors.textMuted,
    textAlign: "center",
    marginTop: spacing.sm,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: spacing.md,
  },
  chip: {
    borderRadius: 20,
    borderWidth: 1.5,
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginRight: 8,
  },
  chipText: {
    fontSize: 14,
    fontWeight: "600",
  },
  dots: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
    paddingVertical: spacing.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.border,
  },
});
