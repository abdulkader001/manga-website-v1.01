import { describe, it, expect } from "vitest";
import { extractLinks, firstLink } from "./links";

describe("links from pasted text", () => {
  it("finds every address once, without trailing punctuation", () => {
    const text = "One: https://a.example/manga/x, two (https://b.example/c?id=2).\nhttps://a.example/manga/x";
    expect(extractLinks(text)).toEqual(["https://a.example/manga/x", "https://b.example/c?id=2"]);
  });

  it("keeps a bare address when the text has no link", () => {
    expect(firstLink("  example.com/manga/x ")).toBe("example.com/manga/x");
    expect(firstLink("Title https://a.example/x")).toBe("https://a.example/x");
  });
});
