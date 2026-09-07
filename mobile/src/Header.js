// ============================================================
// UtiliVault Field — Professional Header v2
// Clean top bar with logo, back navigation, and screen context.
// ============================================================

import React from "react";
import { Image, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { colors, shadows, spacing, typography } from "./theme";

const LOGO_SIZE = 28;

export default function Header({ title, subtitle, onBack, right }) {
  return (
    <View style={s.bar}>
      {onBack ? (
        <TouchableOpacity onPress={onBack} style={s.backBtn} hitSlop={12} activeOpacity={0.7}>
          <Text style={s.backTxt}>‹</Text>
        </TouchableOpacity>
      ) : (
        <View style={s.logoWrap}>
          <Image
            source={require("../../assets/favicon.png")}
            style={s.logo}
            resizeMode="contain"
          />
        </View>
      )}

      <View style={s.titleWrap}>
        <Text style={s.title} numberOfLines={1}>{title}</Text>
        {!!subtitle && <Text style={s.subtitle} numberOfLines={1}>{subtitle}</Text>}
      </View>

      {right ? (
        <View style={s.actionWrap}>{right}</View>
      ) : (
        <View style={s.actionWrap} />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    backgroundColor: colors.bgElevated,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(245,158,11,0.25)",
    ...shadows.sm,
  },
  backBtn: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: colors.surfaceLight,
  },
  backTxt: {
    color: colors.accent,
    fontSize: 32,
    lineHeight: 36,
    fontWeight: "600",
    marginTop: -2,
  },
  logoWrap: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  logo: {
    width: LOGO_SIZE,
    height: LOGO_SIZE,
  },
  titleWrap: {
    flex: 1,
    alignItems: "center",
    paddingHorizontal: spacing.sm,
  },
  title: {
    ...typography.h3,
    color: colors.text,
    textAlign: "center",
  },
  subtitle: {
    ...typography.caption,
    color: colors.textDim,
    textAlign: "center",
    marginTop: 2,
  },
  actionWrap: {
    width: 44,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
});
