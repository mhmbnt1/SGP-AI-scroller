import { useLocalSearchParams } from "expo-router";

import { ItemDetailScreen } from "@/screens/item-detail";

export default function Item() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <ItemDetailScreen id={String(id)} />;
}
