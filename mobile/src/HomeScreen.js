// ============================================================
// UtiliVault Field — Home Screen v2
// Welcome area, connection status, quick-action cards, recent list.
// ============================================================

import React, { useCallback, useEffect, useState } from "react";
import {
  FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View,
} from "react-native";
import { getSettings, health, listCards } from "./api";
import { Button, Card, EmptyState, StatusBadge } from "./components";
import { colors, shadows, spacing, typography } from "./theme";

export default function HomeScreen({ onNewCard, onOpenCard }) {
  const [cards, setCards] = useState([]);
  const [status, setStatus] = useState({ text: "Connecting…", type: "info" });
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    if (!getSettings().serverUrl) {
      setStatus({ text: "No server set — open Settings", type: "warning" });
      setCards([]);
      setRefreshing(false);
      return;
    }
    try {
      const h = await health();
      setStatus({
        text: `Connected — ${h.cards} cards on file · Drive ${h.drive}`,
        type: "online",
      });
      const r = await listCards();
      setCards(r.cards || []);
    } catch (e) {
      setStatus({
        text: `Offline — ${String(e.message || e)}`,
        type: "offline",
      });
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const statusLabel = {
    online: status.text,
    offline: status.text,
    warning: status.text,
    info: status.text,
  }[status.type] || status.text;

  return (
    <View style={{ flex: 1 }}>
      {/* Welcome / Quick Action Area */}
      <View style={s.welcome}>
        <Text style={s.welcomeTitle}>UtiliVault Field</Text>
        <Text style={s.welcomeSub}>Example Utility · Water & Sewer Tie Cards</Text>

        <View style={s.statusRow}>
          <StatusBadge status={status.type} label={statusLabel} />
        </View>

        <Button
          title="＋  New Tie Card"
          onPress={onNewCard}
          variant="primary"
          size="lg"
          style={s.newBtn}
        />
      </View>

      {/* Recent Cards List */}
      <View style={s.listArea}>
        <Text style={s.listHdr}>
          RECENT CARDS  ({cards.length})
        </Text>

        <FlatList
          data={cards}
          keyExtractor={(c) => c.base}
          contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: 20 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={refresh}
              tintColor={colors.accent}
              colors={[colors.accent]}
            />
          }
          ListEmptyComponent={
            <EmptyState
              icon="📋"
              title={refreshing ? "Loading cards…" : "No cards yet"}
              subtitle={refreshing ? "" : "Pull down to refresh or create your first card."}
            />
          }
          renderItem={({ item }) => (
            <Card onPress={() => onOpenCard(item)} style={s.row}>
              {/* Registry badge */}
              <View style={s.regBadge}>
                <Text style={s.regBadgeTxt}>{item.reg_no || "—"}</Text>
                <Text style={s.regBadgeLbl}>REG</Text>
              </View>

              {/* Card info */}
              <View style={{ flex: 1 }}>
                <Text style={s.addr} numberOfLines={1}>{item.address || item.base}</Text>
                <View style={s.metaRow}>
                  <Text style={s.meta}>{item.pages} page{item.pages === 1 ? "" : "s"}</Text>
                  {item.has_photo_page && (
                    <View style={s.tag}>
                      <Text style={s.tagText}>📷 Photo</Text>
                    </View>
                  )}
                  {item.source === "mobile" && (
                    <View style={[s.tag, { backgroundColor: "rgba(6,182,212,0.15)", borderColor: colors.water }]}>
                      <Text style={[s.tagText, { color: colors.water }]}>📱 Mobile</Text>
                    </View>
                  )}
                </View>
              </View>

              {/* Chevron */}
              <Text style={s.chev}>›</Text>
            </Card>
          )}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  welcome: {
    backgroundColor: colors.bgElevated,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xl,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    ...shadows.md,
  },
  welcomeTitle: {
    ...typography.h1,
    textAlign: "center",
  },
  welcomeSub: {
    ...typography.bodySmall,
    textAlign: "center",
    marginTop: 4,
  },
  statusRow: {
    alignItems: "center",
    marginTop: spacing.md,
    marginBottom: spacing.lg,
  },
  newBtn: {
    ...shadows.glowAccent,
  },
  listArea: {
    flex: 1,
    paddingTop: spacing.md,
  },
  listHdr: {
    ...typography.label,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: spacing.md,
    paddingVertical: 12,
    gap: 12,
  },
  regBadge: {
    backgroundColor: colors.bg,
    borderColor: colors.accentDark,
    borderWidth: 1.5,
    borderRadius: 10,
    minWidth: 56,
    paddingHorizontal: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  regBadgeTxt: {
    color: colors.accent,
    fontWeight: "800",
    fontSize: 15,
  },
  regBadgeLbl: {
    color: colors.textMuted,
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1,
    marginTop: 1,
  },
  addr: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 4,
    gap: 8,
  },
  meta: {
    color: colors.textDim,
    fontSize: 12,
  },
  tag: {
    backgroundColor: "rgba(16,185,129,0.15)",
    borderColor: colors.success,
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  tagText: {
    color: colors.success,
    fontSize: 10,
    fontWeight: "700",
  },
  chev: {
    color: colors.textDim,
    fontSize: 22,
    paddingLeft: 2,
  },
});
