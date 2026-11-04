import Constants from "expo-constants";
import { Platform } from "react-native";

/**
 * Backend address per environment. A phone's "localhost" is the phone, not the PC.
 *
 * - Android emulator: 10.0.2.2 maps to the host machine.
 * - iOS simulator: shares the host network, so localhost works.
 * - Physical device: set EXPO_PUBLIC_API_URL=http://<your-pc-lan-ip>:8000 (same Wi-Fi) or an HTTPS URL.
 *   Cleartext HTTP is only acceptable on a trusted LAN during development; production must be HTTPS
 *   (certificate validation is never disabled).
 */
export function apiBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  // Expo Go / dev client: derive the host from the Metro bundler URL (the PC's LAN IP).
  const host = Constants.expoConfig?.hostUri?.split(":")[0];
  if (host && !["localhost", "127.0.0.1"].includes(host)) return `http://${host}:8000`;
  if (Platform.OS === "android") return "http://10.0.2.2:8000";
  return "http://localhost:8000";
}
