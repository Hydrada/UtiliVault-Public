// ============================================================
// UtiliVault Field — Form Screen v2
// Professional tie-card form with improved sections, progress,
// symbol keys, and visual hierarchy.
// ============================================================

import React, { useState } from "react";
import {
  ActivityIndicator, Alert, Image, KeyboardAvoidingView, Platform,
  ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { submitCard } from "./api";
import { Button, Card, Chip, Section } from "./components";
import { colors, input, labelStyle, shadows, spacing, typography } from "./theme";

const MATERIALS = ["Copper", "Lead", "Galv", "Cast Iron", "DI", "PVC", "HDPE"];

function todayStr() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}/${dd}/${d.getFullYear()}`;
}

function maskDate(v) {
  const d = String(v).replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}/${d.slice(2)}`;
  return `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`;
}

const EMPTY = {
  address: "", reg_no: "", contractor: "Demo Contractor", date: todayStr(), inspected_by: "Morgan",
  main_material: "", main_size: "",
  service_main_to_curb: "", diameter_service: "", service_curb_to_house: "",
  left: "", right: "", vertical: "", curb_to_house: "",
  ref_label: "", ref_number: "", comments: "",
};

// ── Field Component ─────────────────────────────────────────
function Field({ lbl, value, onChange, symbols, mask, style, ...props }) {
  const [focused, setFocused] = useState(false);
  const handle = (v) => onChange(mask === "date" ? maskDate(v) : v);

  return (
    <View>
      <Text style={labelStyle}>{lbl}</Text>
      <TextInput
        style={[input, focused && s.inputFocused, style]}
        value={value}
        onChangeText={handle}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholderTextColor={colors.textMuted}
        {...props}
      />
      {!!symbols && (
        <View style={s.symRow}>
          {symbols.map(({ ch, hint }) => (
            <TouchableOpacity
              key={ch}
              style={s.symKey}
              onPress={() => onChange((value || "") + ch)}
              activeOpacity={0.7}
            >
              <Text style={s.symCh}>{ch}</Text>
              {!!hint && <Text style={s.symHint}>{hint}</Text>}
            </TouchableOpacity>
          ))}
          <TouchableOpacity
            style={[s.symKey, s.symDel]}
            onPress={() => onChange(String(value || "").slice(0, -1))}
            activeOpacity={0.7}
          >
            <Text style={s.symCh}>⌫</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

const FEET_INCHES = [
  { ch: "'", hint: "ft" },
  { ch: '"', hint: "in" },
  { ch: "-", hint: "" },
];
const INCHES_ONLY = [{ ch: '"', hint: "in" }];

function MeasureField(props) {
  return <Field keyboardType="numeric" symbols={FEET_INCHES} {...props} />;
}

function MaterialField({ lbl, value, onChange }) {
  return (
    <View style={{ marginTop: 4 }}>
      <Field
        lbl={lbl}
        value={value}
        onChange={onChange}
        placeholder="Type or tap a material"
      />
      <View style={s.chipRow}>
        {MATERIALS.map((m) => (
          <Chip
            key={m}
            label={m}
            active={value === m}
            onPress={() => onChange(value === m ? "" : m)}
          />
        ))}
      </View>
    </View>
  );
}

// ── Main Form Screen ────────────────────────────────────────
export default function FormScreen({ initial, previousBase, keepPhoto, onDone }) {
  const [f, setF] = useState({ ...EMPTY, ...(initial || {}) });
  const [photoUri, setPhotoUri] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeSection, setActiveSection] = useState(0);

  const set = (k) => (v) => setF((prev) => ({ ...prev, [k]: v }));

  async function pickPhoto(fromCamera) {
    const fn = fromCamera
      ? ImagePicker.launchCameraAsync
      : ImagePicker.launchImageLibraryAsync;
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Camera blocked", "Allow camera access in phone settings.");
        return;
      }
    }
    const res = await fn({ mediaTypes: ["images"], quality: 0.8 });
    if (!res.canceled && res.assets?.length) setPhotoUri(res.assets[0].uri);
  }

  async function submit() {
    if (!f.address.trim() && !f.reg_no.trim()) {
      Alert.alert("Almost there", "Enter at least an Address or a Reg No so the card has a name.");
      return;
    }
    setBusy(true);
    try {
      const result = await submitCard(f, photoUri, previousBase);
      onDone(result, f);
    } catch (e) {
      Alert.alert("Submit failed", String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  const SECTIONS = [
    { title: "Header Info", icon: "🪪", index: 0 },
    { title: "Pipe Details", icon: "🔧", index: 1 },
    { title: "Measurements", icon: "📐", index: 2 },
    { title: "Photo & Submit", icon: "📷", index: 3 },
  ];

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 40 }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* Section Tabs */}
        <View style={s.tabRow}>
          {SECTIONS.map((sec) => (
            <TouchableOpacity
              key={sec.index}
              style={[s.tab, activeSection === sec.index && s.tabActive]}
              onPress={() => setActiveSection(sec.index)}
              activeOpacity={0.8}
            >
              <Text style={[s.tabText, activeSection === sec.index && s.tabTextActive]}>
                {sec.icon} {sec.title}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* SECTION 0: HEADER */}
        {activeSection === 0 && (
          <Section title="Header Information" icon="🪪">
            <Field lbl="Address" value={f.address} onChange={set("address")}
                   placeholder="12 Maple St" autoCapitalize="words" />
            <Field lbl="Registry Number" value={f.reg_no} onChange={set("reg_no")}
                   placeholder="8443" keyboardType="numeric" />
            <Field lbl="Contractor" value={f.contractor} onChange={set("contractor")}
                   autoCapitalize="words" />
            <Field lbl="Date" value={f.date} onChange={set("date")}
                   placeholder="MM/DD/YYYY" keyboardType="numeric" mask="date" />
            <Field lbl="Inspected By" value={f.inspected_by} onChange={set("inspected_by")}
                   autoCapitalize="words" />
          </Section>
        )}

        {/* SECTION 1: PIPE */}
        {activeSection === 1 && (
          <Section title="Pipe Specifications" icon="🔧">
            <MaterialField lbl="Main Material" value={f.main_material} onChange={set("main_material")} />
            <Field lbl="Main Diameter" value={f.main_size} onChange={set("main_size")}
                   placeholder={'8"'} keyboardType="numeric" symbols={INCHES_ONLY} />
            <MaterialField lbl="Service Material (Main to Curb)" value={f.service_main_to_curb}
                           onChange={set("service_main_to_curb")} />
            <Field lbl="Service Diameter" value={f.diameter_service} onChange={set("diameter_service")}
                   placeholder={'1"'} keyboardType="numeric" symbols={INCHES_ONLY} />
            <MaterialField lbl="Service Material (Curb to House)" value={f.service_curb_to_house}
                           onChange={set("service_curb_to_house")} />
          </Section>
        )}

        {/* SECTION 2: MEASUREMENTS */}
        {activeSection === 2 && (
          <Section title="Tie Measurements" icon="📐">
            <MeasureField lbl="LS — Left diagonal" value={f.left} onChange={set("left")}
                          placeholder={"44'-2\""} />
            <MeasureField lbl="RS — Right diagonal" value={f.right} onChange={set("right")}
                          placeholder={"51'-8\""} />
            <MeasureField lbl="MC — Main to Curb" value={f.vertical} onChange={set("vertical")}
                          placeholder={"12'-6\""} />
            <MeasureField lbl="CH — Curb to House" value={f.curb_to_house} onChange={set("curb_to_house")}
                          placeholder={"38'"} />
            <Field lbl="Reference Label (sketch box)" value={f.ref_label} onChange={set("ref_label")}
                   placeholder="Hydrant / Old Conn Path" />
            <MeasureField lbl="Reference Number" value={f.ref_number} onChange={set("ref_number")} />

            <Section title="Notes" icon="📝" style={{ marginTop: spacing.lg, marginBottom: 0 }}>
              <Field lbl="Comments" value={f.comments} onChange={set("comments")}
                     multiline numberOfLines={3}
                     style={{ minHeight: 80, textAlignVertical: "top" }} />
            </Section>
          </Section>
        )}

        {/* SECTION 3: PHOTO & SUBMIT */}
        {activeSection === 3 && (
          <>
            <Section title="House Photo" icon="📷">
              {photoUri ? (
                <Image source={{ uri: photoUri }} style={s.photo} resizeMode="cover" />
              ) : keepPhoto ? (
                <View style={s.photoNoteBox}>
                  <Text style={s.photoNote}>📷 Keeping existing photo</Text>
                  <Text style={s.photoNoteSub}>Take a new photo below to replace it.</Text>
                </View>
              ) : (
                <View style={s.photoNoteBox}>
                  <Text style={s.photoNote}>Optional house photo</Text>
                  <Text style={s.photoNoteSub}>Never printed; becomes page 3 of the digital card.</Text>
                </View>
              )}

              <View style={s.photoBtnRow}>
                <Button
                  title="Camera"
                  onPress={() => pickPhoto(true)}
                  variant="secondary"
                  size="md"
                  style={{ flex: 1 }}
                />
                <Button
                  title="Library"
                  onPress={() => pickPhoto(false)}
                  variant="outline"
                  size="md"
                  style={{ flex: 1 }}
                />
              </View>
            </Section>

            <Button
              title={previousBase ? "🔄 Regenerate Card" : "✓ Submit — Make the Card"}
              onPress={submit}
              variant="primary"
              size="lg"
              loading={busy}
              disabled={busy}
              style={[s.submitBtn, shadows.glowAccent]}
            />
          </>
        )}

        {/* Navigation between sections */}
        <View style={s.navRow}>
          {activeSection > 0 && (
            <Button
              title="← Previous"
              onPress={() => setActiveSection(activeSection - 1)}
              variant="ghost"
              size="md"
            />
          )}
          {activeSection < 3 && (
            <Button
              title="Next →"
              onPress={() => setActiveSection(activeSection + 1)}
              variant="outline"
              size="md"
              style={{ marginLeft: "auto" }}
            />
          )}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  tabRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  tab: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
    ...shadows.sm,
  },
  tabText: {
    fontSize: 13,
    fontWeight: "600",
    color: colors.textDim,
  },
  tabTextActive: {
    color: "#0f172a",
    fontWeight: "700",
  },
  inputFocused: {
    borderColor: colors.accent,
    ...shadows.glowAccent,
  },
  symRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 6,
  },
  symKey: {
    backgroundColor: colors.surfaceLight,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    minWidth: 56,
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "center",
    gap: 4,
  },
  symDel: {
    marginLeft: "auto",
    minWidth: 64,
  },
  symCh: {
    color: colors.accent,
    fontSize: 20,
    fontWeight: "800",
  },
  symHint: {
    color: colors.textDim,
    fontSize: 11,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 8,
  },
  photo: {
    width: "100%",
    height: 200,
    borderRadius: 12,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  photoNoteBox: {
    backgroundColor: colors.bg,
    borderRadius: 10,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
  },
  photoNote: {
    color: colors.textDim,
    fontSize: 14,
    fontWeight: "600",
  },
  photoNoteSub: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  photoBtnRow: {
    flexDirection: "row",
    gap: spacing.md,
  },
  submitBtn: {
    marginTop: spacing.lg,
  },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: spacing.xl,
  },
});
