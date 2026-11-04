import type { RecommendationOut } from "@focusfeed/contracts";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecommendationCard } from "./recommendation-card";

const rec: RecommendationOut = {
  id: "r1", rank: 1, platform: "youtube", score: 0.8, components: { interest_match: 1, novelty: 1 }, explanation: "Matches your interests: cooking.",
  summary: "Transcript excerpt", topics: ["cooking"], analysis_kind: "transcript_supported", estimated_seconds: 540, duration_known: true,
  seen: false, hidden: false, saved: false,
  item: { id: "i1", platform: "youtube", external_id: "x", canonical_url: "https://www.youtube.com/watch?v=x", creator_handle: "chef", creator_name: "Chef", title: "Stir fry",
    caption: "", language: "en", duration_seconds: 540, published_at: null, thumbnail_url: null, is_synthetic: true },
};

describe("RecommendationCard", () => {
  it("renders source link with safe rel, synthetic badge and explanation on demand", () => {
    render(<RecommendationCard rec={rec} />);
    const link = screen.getByRole("link", { name: /open on youtube/i });
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch?v=x");
    expect(screen.getByText("synthetic demo")).toBeInTheDocument();
    expect(screen.getByText("9 min")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /why this/i }));
    expect(screen.getByText(/matches your interests/i)).toBeInTheDocument();
  });

  it("prevents duplicate submissions while a feedback request is in flight", async () => {
    let resolve: () => void = () => {};
    const onFeedback = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    render(<RecommendationCard rec={rec} onFeedback={onFeedback} />);
    const btn = screen.getByRole("button", { name: /mark relevant/i });
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(onFeedback).toHaveBeenCalledTimes(1);
    expect(btn).toBeDisabled();
    resolve();
  });
});
