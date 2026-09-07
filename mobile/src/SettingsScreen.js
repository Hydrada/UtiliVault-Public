// ============================================================
// UtiliVault Field — Settings Screen v2
// Server config, connection test, and app info.
// ============================================================

import React, { useState } from "react";
import {
  Alert, Image, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View,
} from "react-native";
import { getSettings, health, saveSettings } from "./api";
import { Button, Card, StatusBadge } from "./components";
import { colors, input, shadows, spacing, typography } from "./theme";

export default function SettingsScreen({ onBack }) {
  const init = getSettings();
  const [serverUrl, setServerUrl] = useState(init.serverUrl);
  const [apiKey, setApiKey] = useState(init.apiKey);
  const [testResult, setTestResult] = useState(null);

  async function save() {
    await saveSettings({ serverUrl: serverUrl.trim(), apiKey: apiKey.trim() });
    onBack();
  }

  async function test() {
    await saveSettings({ serverUrl: serverUrl.trim(), apiKey: apiKey.trim() });
    setTestResult({ type: "info", text: "Testing connection…" });
    try {
      const h = await health();
      setTestResult({
        type: "online",
        text: `Connected — ${h.cards} cards · Drive ${h.drive} · Auth ${h.auth}`,
      });
    } catch (e) {
      setTestResult({
        type: "offline",
        text: String(e.message || e),
      });
      Alert.alert(
        "Connection failed",
        "Check that the UtiliVault PC is running and the phone is on the same network."
      );
    }
  }

  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.lg }}>
      {/* App branding */}
      <View style={s.brand}>
        <Image
          source={require("../../assets/favicon.png")}
          style={s.brandLogo}
          resizeMode="contain"
        />
        <Text style={s.brandTitle}>UtiliVault Field</Text>
        <Text style={s.brandSub}>v1.2.0  ·  Example Utility</Text>
      </View>

      {/* Server config card */}
      <Card>
        <Text style={s.sectionTitle}>🔌 Server Configuration</Text>
        <Text style={s.help}>
          Set the UtiliVault PC's address. Must be on the same Wi-Fi or Tailscale network.
        </Text>

        <Text style={typography.label}>Server Address</Text>
        <TextInput
          style={input}
          value={serverUrl}
          onChangeText={setServerUrl}
          placeholder="YOUR_SERVER_HOST:8791"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />

        <Text style={[typography.label, { marginTop: spacing.lg }]}>API Key (optional)</Text>
        <TextInput
          style={input}
          value={apiKey}
          onChangeText={setApiKey}
          placeholder="Only if UTILIVAULT_API_KEY is set on PC"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />

        {testResult && (
          <View style={{ marginTop: spacing.md }}>
            <StatusBadge status={testResult.type} label={testResult.text} />
          </View>
        )}

        <Button
          title="Test Connection"
          onPress={test}
          variant="secondary"
          size="md"
          style={{ marginTop: spacing.lg }}
        />
      </Card>

      {/* Save button */}
      <Button
        title="Save Settings"
        onPress={save}
        variant="primary"
        size="lg"
        style={{ marginTop: spacing.lg, ...shadows.glowAccent }}
      />

      {/* Help / Tips */}
      <Card style={{ marginTop: spacing.lg }}>
        <Text style={s.sectionTitle}>💡 Quick Tips</Text>
        <Text style={s.tip}>• Find the PC address in the api_server.py startup message</Text>
        <Text style={s.tip}>• Both devices must be on the same network</Text>
        <Text style={s.tip}>• Tailscale works from anywhere once connected</Text>
        <Text style={s.tip}>• The API key is set in the PC's .env file</Text>
      </Card>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  brand: {
    alignItems: "center",
    marginBottom: spacing.xl,
    paddingTop: spacing.md,
  },
  brandLogo: {
    width: 64,
    height: 64,
    marginBottom: spacing.md,
  },
  brandTitle: {
    ...typography.h2,
  },
  brandSub: {
    ...typography.bodySmall,
    color: colors.textMuted,
    marginTop: 2,
  },
  sectionTitle: {
    ...typography.h3,
    color: colors.accent,
    marginBottom: spacing.sm,
  },
  help: {
    ...typography.bodySmall,
    color: colors.textDim,
    marginBottom: spacing.lg,
    lineHeight: 20,
  },
  tip: {
    ...typography.bodySmall,
    color: colors.textDim,
    marginBottom: spacing.sm,
    lineHeight: 20,
  },
});
