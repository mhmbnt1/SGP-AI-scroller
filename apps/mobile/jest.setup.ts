import "@testing-library/react-native";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (k: string) => mockSecure.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => { mockSecure.set(k, v); }),
  deleteItemAsync: jest.fn(async (k: string) => { mockSecure.delete(k); }),
}));

const mockAsync = new Map<string, string>();
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async (k: string) => mockAsync.get(k) ?? null),
  setItem: jest.fn(async (k: string, v: string) => { mockAsync.set(k, v); }),
  removeItem: jest.fn(async (k: string) => { mockAsync.delete(k); }),
  getAllKeys: jest.fn(async () => Array.from(mockAsync.keys())),
  multiRemove: jest.fn(async (ks: string[]) => { ks.forEach((k) => mockAsync.delete(k)); }),
}));

jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
    useLocalSearchParams: () => ({}),
    Link: ({ children }: { children: unknown }) => React.createElement(React.Fragment, null, children),
    Redirect: () => null,
    Stack: { Screen: () => null },
  };
});
