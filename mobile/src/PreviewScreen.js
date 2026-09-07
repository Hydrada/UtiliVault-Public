// ============================================================
// UtiliVault Field — Preview Screen v2
// Card page viewer with dots, zoom modal, and action buttons.
// ============================================================

import React, { useMemo, useState } from "react";
import {
  Dimensions, FlatList, Image, Modal, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { headers, pageUrl } from "./api";
import { Button, Card, ProgressDots } from "./components";
import { colors, shadows, spacing, typography } from "./theme";

const PAGE_NAMES = ["FRONT PAGE", "BACK — TIE SKETCH", "PROPERTY PHOTO"];
const PAGE_ICONS = ["📄", "📐", "📷"];

export default function PreviewScreen({ base, pageUrls, driveStatus, onEdit, onDone }) {
  const { width } = Dimensions.get("window");
  const [pageIx, setPageIx] = useState(0);
  const [zoomUrl, setZoomUrl] = useState(null);
  const stamp = useMemo(() => Date.now(), [pageUrls]);

  const pages = pageUrls.map((u, i) => ({
    key: String(i),
    name: PAGE_NAMES[i] || `PAGE ${i + 1}`,
    icon: PAGE_ICONS[i] || "📄",
    url: `${pageUrl(u)}?t=${stamp}`,
  }));

  const driveLabel =
    driveStatus === "uploaded" ? "✓ Saved to Drive folder 14"
    : driveStatus === "drive-off" ? "Drive upload disabled"
    : driveStatus ? `Drive: ${driveStatus}`
    : "";
  const driveColor = driveStatus === "uploaded" ? colors.success : colors.textDim;

  return (
    <View style={{ flex: 1 }}>
      {/* Page header */}
      <View style={s.header}>
        <Text style={s.title} numberOfLines={1}>{base}</Text>
        {!!driveLabel && (
          <View style={s.driveBadge}>
            <Text style={[s.driveText, { color: driveColor }]}>{driveLabel}</Text>
          </View>
        )}
      </View>

      {/* Horizontal page swiper */}
      <FlatList
        data={pages}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        keyExtractor={(p) => p.key}
        onMomentumScrollEnd={(e) =>
          setPageIx(Math.round(e.nativeEvent.contentOffset.x / width))
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            activeOpacity={0.9}
            style={{ width, padding: 12 }}
            onPress={() => setZoomUrl(item.url)}
          >
            <View style={s.pageHeader}>
              <Text style={s.pageIcon}>{item.icon}</Text>
              <Text style={s.pageName}>{item.name}</Text>
            </View>

            <Card style={s.pageCard}>
              <Image
                source={{ uri: item.url, headers: headers() }}
                style={s.pageImg}
                resizeMode="contain"
              />
            </Card>

            <Text style={s.hint}>Tap image to zoom · swipe for next page</Text>
          </TouchableOpacity>
        )}
      />

      {/* Page indicator dots */}
      <ProgressDots total={pages.length} current={pageIx} />

      {/* Action buttons */}
      <View style={s.actions}>
        <Button
          title="✏️ Edit"
          onPress={onEdit}
          variant="outline"
          size="md"
          style={{ flex: 1 }}
        />
        <Button
          title="✓ Looks Good — Done"
          onPress={onDone}
          variant="primary"
          size="md"
          style={{ flex: 2 }}
        />
      </View>

      {/* Zoom modal */}
      <Modal visible={!!zoomUrl} transparent onRequestClose={() => setZoomUrl(null)}>
        <TouchableOpacity
          style={s.zoomWrap}
          activeOpacity={1}
          onPress={() => setZoomUrl(null)}
        >
          {zoomUrl && (
            <Image
              source={{ uri: zoomUrl, headers: headers() }}
              style={s.zoomImg}
              resizeMode="contain"
            />
          )}
          <Text style={[s.hint, { color: "#ccc" }]}>Tap anywhere to close</Text>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: 10,
    paddingBottom: 6,
  },
  title: {
    ...typography.h2,
    textAlign: "center",
  },
  driveBadge: {
    alignSelf: "center",
    marginTop: 4,
    backgroundColor: colors.surface,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  driveText: {
    fontSize: 12,
    fontWeight: "600",
  },
  pageHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
    gap: 6,
  },
  pageIcon: {
    fontSize: 16,
  },
  pageName: {
    ...typography.label,
    color: colors.accent,
    marginTop: 0,
    marginBottom: 0,
    textAlign: "center",
  },
  pageCard: {
    padding: 8,
    backgroundColor: "#ffffff",
    alignItems: "center",
    justifyContent: "center",
  },
  pageImg: {
    width: "100%",
    height: width * 0.65,
    borderRadius: 6,
  },
  hint: {
    color: colors.textDim,
    fontSize: 11,
    textAlign: "center",
    marginTop: 8,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.md,
    padding: spacing.lg,
    paddingTop: 0,
  },
  zoomWrap: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.92)",
    justifyContent: "center",
    padding: 10,
  },
  zoomImg: {
    width: "100%",
    height: "82%",
  },
});
