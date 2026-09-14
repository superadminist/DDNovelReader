const AUTO_TEXT_COLORS = {
  light: "#292B31",
  sepia: "#40372C",
  dark: "#F0F2F6",
};

export function floatingPickerColor(settings) {
  if (/^#[0-9A-Fa-f]{6}$/.test(settings?.textColor || "")) {
    return settings.textColor.toUpperCase();
  }
  return AUTO_TEXT_COLORS[settings?.background] || AUTO_TEXT_COLORS.light;
}

export function floatingTextColorPatch(value) {
  if (!/^#[0-9A-Fa-f]{6}$/.test(value || "")) return null;
  return { textColor: value.toUpperCase() };
}

export function floatingFontWheelChange(fontSize, followReaderFont, deltaY) {
  if (!deltaY) return null;
  const current = Math.max(14, Math.min(40, Number(fontSize) || 22));
  const next = Math.max(14, Math.min(40, current + (deltaY < 0 ? 1 : -1)));
  if (next === current && !followReaderFont) return null;
  return {
    fontSize: next,
    immediate: Boolean(followReaderFont),
    patch: followReaderFont
      ? { followReaderFont: false, fontSize: next }
      : { fontSize: next },
  };
}

export function mergeFloatingState(state, patch) {
  if (!state) return state;
  return { ...state, settings: { ...state.settings, ...patch } };
}

export function settingsPatchIds(scope, patch) {
  return Object.keys(patch || {}).map((key) => `${scope}.${key}`);
}
