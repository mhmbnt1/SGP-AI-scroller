import type { RecommendationOut } from "@focusfeed/contracts";
import { fireEvent, render } from "@testing-library/react-native";

import { RecommendationCard } from "@/components/recommendation-card";

jest.mock("expo-web-browser", () => ({ openBrowserAsync: jest.fn(async () => ({ type: "dismiss" })) }));

const rec: RecommendationOut = {
  id: "r1", rank: 1, platform: "youtube", score: 0.8, components: { interest_match: 1, novelty: 1 }, explanation: "Matches your interests: cooking.",
  summary: "Transcript excerpt", topics: ["cooking"], analysis_kind: "transcript_supported", estimated_seconds: 540, duration_known: true, seen: false, hidden: false, saved: false,
  item: { id: "i1", platform: "youtube", external_id: "x", canonical_url: "https://www.youtube.com/watch?v=x", creator_handle: "chef", creator_name: "Chef", title: "Stir fry", caption: "", language: "en", duration_seconds: 540, published_at: null, thumbnail_url: null, is_synthetic: true },
};

describe("RecommendationCard (native)", () => {
  it("renders title, synthetic badge and duration; shows explanation on demand", async () => {
    // RNTL 14 renders asynchronously under React 19 concurrent mode.
    const { getByText, getByLabelText } = await render(<RecommendationCard rec={rec} />);
    expect(getByText("Stir fry")).toBeTruthy();
    expect(getByText("synthetic demo")).toBeTruthy();
    expect(getByText("9 min")).toBeTruthy();
    await fireEvent.press(getByLabelText("Why this?"));
    expect(getByText(/Matches your interests/)).toBeTruthy();
  });

  it("opens the source in the system browser and prevents duplicate feedback submissions", async () => {
    const WebBrowser = require("expo-web-browser");
    let resolve: () => void = () => {};
    const onFeedback = jest.fn(() => new Promise<void>((r) => { resolve = r; }));
    const { getByLabelText } = await render(<RecommendationCard rec={rec} onFeedback={onFeedback} />);
    await fireEvent.press(getByLabelText("Open on youtube"));
    expect(WebBrowser.openBrowserAsync).toHaveBeenCalledWith("https://www.youtube.com/watch?v=x");
    await fireEvent.press(getByLabelText("👍 Relevant"));
    await fireEvent.press(getByLabelText("👍 Relevant"));
    expect(onFeedback).toHaveBeenCalledTimes(1);
    resolve();
  });
});
