import { expect, test } from "@playwright/test";

const apiOrigin = process.env.PRISM_BROWSER_API_ORIGIN ?? "http://127.0.0.1:8000";
const transcriptVideo = process.env.PRISM_BROWSER_TRANSCRIPT_VIDEO_ID;
const silentVideo = process.env.PRISM_BROWSER_SILENT_VIDEO_ID;
let collectionId = "";

test.afterEach(async ({ request }) => {
  if (!collectionId) return;
  await request.delete(`${apiOrigin}/collections/${collectionId}`, { headers: { "X-Prism-Request": "1" } });
  collectionId = "";
});

test("inspects original spoken segments from a transcript result", async ({ page }) => {
  test.skip(!transcriptVideo, "Set PRISM_BROWSER_TRANSCRIPT_VIDEO_ID to a ready captioned video");
  await page.route(`${apiOrigin}/search?**`, (route) => route.fulfill({ json: {
    state: "results", results: [{
      video_id: transcriptVideo, video_title: "Captioned source", start_seconds: 55,
      end_seconds: 65, excerpt: "Suggested passage", evidence: ["transcript"],
      preview_time_seconds: 55, preview_url: `/videos/${transcriptVideo}/frames/0`,
      playback_url: `/videos/${transcriptVideo}/media`,
    }], video_results: [], provisional: true,
  } }));
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Search question" }).fill("source words");
  await page.getByRole("button", { name: /^Search/ }).click();
  await page.locator(".search-section .result-card").first().getByRole("button", { name: "Inspect evidence" }).click();
  const inspector = page.getByRole("region", { name: "Evidence from Captioned source" });
  await expect(inspector.getByText("The search matched transcript text. These are the original nearby segments.")).toBeVisible();
  await expect(inspector.locator(".evidence-segments li").first()).toBeVisible();
  await expect(inspector.getByText(/Context frame/).first()).toBeVisible();
  await expect(inspector.getByText("Search matches are leads, not verified answers.", { exact: false })).toBeVisible();
  await expect(inspector.locator("video")).toBeVisible();
});

test("labels a matching frame and inspects a saved silent range", async ({ page, request }) => {
  test.skip(!silentVideo, "Set PRISM_BROWSER_SILENT_VIDEO_ID to a ready silent video");
  await page.route(`${apiOrigin}/search?**`, (route) => route.fulfill({ json: {
    state: "results", results: [{
      video_id: silentVideo, video_title: "Silent source", start_seconds: 17.5,
      end_seconds: 22.5, excerpt: null, evidence: ["frame"],
      preview_time_seconds: 20, preview_url: `/videos/${silentVideo}/frames/4`,
      playback_url: `/videos/${silentVideo}/media`,
    }], video_results: [], provisional: true,
  } }));
  const created = await request.post(`${apiOrigin}/collections`, {
    headers: { "X-Prism-Request": "1" }, data: { title: `Evidence browser ${Date.now()}` },
  });
  expect(created.ok()).toBeTruthy();
  collectionId = (await created.json()).id as string;
    const added = await request.post(`${apiOrigin}/collections/${collectionId}/items`, {
      headers: { "X-Prism-Request": "1" },
      data: { video_id: silentVideo, start_seconds: 17.5, end_seconds: 22.5, note: "Check screen" },
    });
    expect(added.ok()).toBeTruthy();
    await page.goto("/");
    await page.getByRole("combobox", { name: "Collection", exact: true }).selectOption(collectionId);
    await page.getByRole("searchbox", { name: "Search question" }).fill("visible step");
    await expect(page.getByRole("searchbox", { name: "Search question" })).toHaveValue("visible step");
    await page.getByRole("button", { name: /^Search/ }).click();
    await page.locator(".result-card").first().getByRole("button", { name: "Inspect evidence" }).click();
    const resultInspector = page.locator(".search-section .evidence-inspector");
    await expect(resultInspector.getByText(/Matching frame · 0:20/)).toBeVisible();
    await expect(resultInspector.getByText("No transcript is available for this video.")).toBeVisible();

    await page.locator(".collection-item").getByRole("button", { name: "Inspect evidence" }).click();
    const savedInspector = page.locator(".collections .evidence-inspector");
    await expect(savedInspector.getByText(/Context frame · 0:20/)).toBeVisible();
    await savedInspector.getByRole("slider", { name: /Inspect time within range/ }).fill("21");
    await savedInspector.getByRole("button", { name: "Inspect selected time" }).click();
    await expect(savedInspector.getByText(/Inspect time within range: 0:21/)).toBeVisible();
    await expect(savedInspector.getByText("Starts at 0:21 at the inspected time.", { exact: false })).toBeVisible();
});

test("inspects a frame found by an image query", async ({ page }) => {
  test.skip(!silentVideo, "Set PRISM_BROWSER_SILENT_VIDEO_ID to a ready silent video");
  await page.route(`${apiOrigin}/search/visual**`, (route) => route.fulfill({ json: {
    state: "results", results: [{
      video_id: silentVideo, video_title: "Silent source", frame_time_seconds: 20,
      frame_url: `/videos/${silentVideo}/frames/4`,
      playback_url: `/videos/${silentVideo}/media`, query_time_seconds: 0,
    }], skipped_videos: [],
  } }));
  await page.goto("/");
  await page.getByLabel("Screenshot or clip").setInputFiles({
    name: "query.png", mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YjQ7f8AAAAASUVORK5CYII=", "base64"),
  });
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await page.locator(".visual-query .result-card").getByRole("button", { name: "Inspect evidence" }).click();
  const inspector = page.locator(".visual-query .evidence-inspector");
  await expect(inspector.getByText(/Matching frame · 0:20/)).toBeVisible();
  await expect(inspector.getByText("No transcript is available for this video.")).toBeVisible();
});
