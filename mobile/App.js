// UtiliVault Field — app shell. Four screens, hand-rolled navigation
// (no nav library: fewer deps, faster cold start on old field phones).
//
//   home ──＋ New Card──▶ form ──Submit──▶ preview ──Done──▶ home
//     │                   ▲                  │
//     │                   └──── ✏️ Edit ─────┘   (form prefilled, rename-safe)
//     └── tap a card ──▶ preview (fields fetched for later editing)
//
// The Android hardware back button walks the same graph (form -> preview or
// home, preview/settings -> home) instead of quitting the app; it only exits
// from the home screen.

import React, { useCallback, useEffect, useState } from "react";
import { BackHandler, Pressable, SafeAreaView, StatusBar, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { getCard, loadSettings } from "./src/api";
import { colors } from "./src/theme";
import FormScreen from "./src/FormScreen";
import Header from "./src/Header";
import HomeScreen from "./src/HomeScreen";
import PreviewScreen from "./src/PreviewScreen";
import SettingsScreen from "./src/SettingsScreen";

export default function App() {
  const [ready, setReady] = useState(false);
  const [screen, setScreen] = useState("home");
  // Card being viewed/edited:
  //   base, pageUrls, driveStatus, fields (for Edit prefill), keepPhoto
  const [current, setCurrent] = useState(null);
  const [homeKey, setHomeKey] = useState(0);   // bump to force home refresh

  useEffect(() => {
    loadSettings().then((s) => {
      setReady(true);
      if (!s.serverUrl) setScreen("settings");   // first run → point at the PC
    });
  }, []);

  const goHome = useCallback(() => {
    setCurrent(null);
    setHomeKey((k) => k + 1);
    setScreen("home");
  }, []);

  const goBack = useCallback(() => {
    if (screen === "form") {
      if (current) setScreen("preview");
      else goHome();
      return true;
    }
    if (screen === "preview" || screen === "settings") {
      goHome();
      return true;
    }
    return false;   // home: let the OS handle it (exit the app)
  }, [screen, current, goHome]);

  // Android hardware back -> in-app navigation, not app exit.
  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", goBack);
    return () => sub.remove();
  }, [goBack]);

  if (!ready) return <View style={s.root} />;

  async function openCard(summary) {
    try {
      const d = await getCard(summary.base);
      setCurrent({
        base: d.base,
        pageUrls: d.page_urls,
        driveStatus: "",
        fields: d.fields,
        keepPhoto: summary.has_photo_page,
      });
      setScreen("preview");
    } catch (e) {
      console.warn("open card failed", e);
    }
  }

  const headers = {
    home: {
      title: "UtiliVault Field",
      subtitle: "Example Utility · Water Service Tie Cards",
      brand: true,
      right: (
        <Pressable
          onPress={() => setScreen("settings")}
          hitSlop={10}
          style={({ pressed }) => [s.gear, pressed && s.gearPressed]}
        >
          <Ionicons name="settings-outline" size={21} color={colors.textDim} />
        </Pressable>
      ),
    },
    form: {
      title: current ? "Edit Card" : "New Tie Card",
      subtitle: current?.base,
      onBack: goBack,
    },
    preview: { title: "Review Card", subtitle: current?.base, onBack: goBack },
    settings: { title: "Settings", onBack: goBack },
  };

  return (
    <SafeAreaView style={s.root}>
      <StatusBar barStyle="light-content" backgroundColor={colors.panel} />
      <Header {...headers[screen]} />

      {screen === "home" && (
        <HomeScreen
          key={homeKey}
          onNewCard={() => { setCurrent(null); setScreen("form"); }}
          onOpenCard={openCard}
        />
      )}

      {screen === "form" && (
        <FormScreen
          initial={current?.fields}
          previousBase={current?.base}
          keepPhoto={current?.keepPhoto}
          onDone={(result, submittedFields) => {
            setCurrent({
              base: result.base,
              pageUrls: result.page_urls,
              driveStatus: result.drive,
              fields: submittedFields,
              keepPhoto: result.pages >= 3,
            });
            setScreen("preview");
          }}
        />
      )}

      {screen === "preview" && current && (
        <PreviewScreen
          base={current.base}
          pageUrls={current.pageUrls}
          driveStatus={current.driveStatus}
          onEdit={() => setScreen("form")}
          onDone={goHome}
        />
      )}

      {screen === "settings" && <SettingsScreen onBack={goHome} />}

      <Text style={s.footer}>UtiliVault · Example Utility</Text>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  gear: {
    width: 40, height: 40, borderRadius: 12,
    alignItems: "center", justifyContent: "center",
  },
  gearPressed: { backgroundColor: colors.panelLight },
  footer: {
    color: colors.textFaint, fontSize: 10, textAlign: "center",
    paddingVertical: 5, letterSpacing: 0.6,
  },
});
