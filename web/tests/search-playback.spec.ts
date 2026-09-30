import { expect, test } from "@playwright/test";

const apiOrigin = process.env.PRISM_BROWSER_API_ORIGIN ?? "http://127.0.0.1:8000";
const videoId = process.env.PRISM_BROWSER_VIDEO_ID;

test("searches ready transcripts, filters videos, and plays with context", async ({ page }) => {
  test.skip(!videoId, "Set PRISM_BROWSER_VIDEO_ID to a ready, searchable local video");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Search your videos" })).toBeVisible();
  const filter = page.locator(`.video-filters input[value="${videoId}"]`);
  await expect(filter).toBeVisible();
  await page.getByRole("searchbox", { name: "Search question" }).fill("database connection");
  await page.getByRole("button", { name: /^Search/ }).click();
  await expect(page.getByText(/possible match/)).toBeVisible();
  const allCount = await page.locator(".result-card").count();
  expect(allCount).toBeGreaterThan(0);
  await filter.check();
  await expect(page.locator(".result-card").first()).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.locator(".result-card").first()).toBeVisible();
  await page.getByRole("button", { name: "Play this moment" }).first().click();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByText(/Starts at .* three seconds of context/)).toBeVisible();
  const current = await page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime);
  expect(current).toBeGreaterThanOrEqual(0);
});

test("near-zero seek and rapid result selection use the latest passage", async ({ page }) => {
  test.skip(!videoId, "Set PRISM_BROWSER_VIDEO_ID to a ready local video");
  const result = (start: number) => ({
    video_id: videoId, video_title: "Test video", start_seconds: start,
    end_seconds: start + 2, excerpt: `Passage at ${start}`,
    preview_time_seconds: null, preview_url: null,
    playback_url: `/videos/${videoId}/media`,
  });
  await page.route(`${apiOrigin}/search**`, async (route) => {
    await route.fulfill({ json: { state: "results", results: [result(0.5), result(20)], provisional: true } });
  });
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Search question" }).fill("setup");
  await page.getByRole("button", { name: /^Search/ }).click();
  await expect(page.locator(".result-card")).toHaveCount(2);
  await page.getByRole("button", { name: "Play this moment" }).first().click();
  await expect(page.getByText("Starts at 0:00 with up to three seconds of context. Playback continues normally.")).toBeVisible();
  await expect.poll(async () => page.locator("video").evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(1);
  const nearStart = await page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime);
  expect(nearStart).toBeLessThan(3);
  await page.getByRole("button", { name: "Play this moment" }).last().click();
  await expect(page.getByText("Starts at 0:17 with up to three seconds of context. Playback continues normally.")).toBeVisible();
  await expect.poll(async () => page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(16);
  const playingAt = await page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime);
  await expect.poll(async () => page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(playingAt);
});

test("changing the question discards a delayed search response", async ({ page }) => {
  test.skip(!videoId, "Set PRISM_BROWSER_VIDEO_ID to a ready local video");
  await page.route(`${apiOrigin}/search**`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.fulfill({ json: { state: "results", results: [], provisional: true } }).catch(() => {});
  });
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Search question" }).fill("first query");
  await page.getByRole("button", { name: /^Search/ }).click();
  await page.getByRole("searchbox", { name: "Search question" }).fill("edited query");
  await page.waitForTimeout(700);
  await expect(page.getByText(/possible match/)).toHaveCount(0);
});
