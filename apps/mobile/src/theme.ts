/** Design tokens mirroring apps/web/src/app/globals.css. */
import { useColorScheme } from "react-native";

export const palette = {
  light: {
    bg: "#f7f6f2", surface: "#ffffff", surface2: "#efede7", text: "#1b1a17", muted: "#5c5a53", border: "#d9d6cd",
    accent: "#0b6e4f", accentContrast: "#ffffff", accentSoft: "#dcefe6", warn: "#9a5b00", warnSoft: "#fff1d6",
    danger: "#a4262c", dangerSoft: "#fde3e4", infoSoft: "#e3ecf7",
  },
  dark: {
    bg: "#14151a", surface: "#1d1f26", surface2: "#262932", text: "#ecebe6", muted: "#a8a69f", border: "#363943",
    accent: "#4fc08d", accentContrast: "#0c1a14", accentSoft: "#163626", warn: "#f0b35a", warnSoft: "#3a2a10",
    danger: "#ff7b81", dangerSoft: "#3b1a1c", infoSoft: "#1f2a3a",
  },
};

export type Colors = typeof palette.light;
export const space = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32 } as const;
export const radius = { md: 12, sm: 8 } as const;
export const touch = 44;

export function useColors(): Colors {
  const scheme = useColorScheme();
  return scheme === "dark" ? palette.dark : palette.light;
}
