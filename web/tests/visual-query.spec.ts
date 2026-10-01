import { expect, test } from "@playwright/test";

const apiOrigin = process.env.PRISM_BROWSER_API_ORIGIN ?? "http://127.0.0.1:8000";
const videoId = "00000000-0000-4000-8000-000000000001";
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==", "base64");

test("visual image query shows the matched frame and opens its timestamp", async ({ page }) => {
  await page.route(`${apiOrigin}/videos`, async (route) => {
    await route.fulfill({ json: [{
      id: videoId, title: "Product demo", duration_seconds: 42, status: "ready",
      current_step: null, error: null, transcript_state: "none", visual_state: "ready",
      visual_error: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }] });
  });
  await page.route(`${apiOrigin}/search/visual**`, async (route) => {
    expect(route.request().postDataBuffer()?.length).toBeGreaterThan(0);
    expect(route.request().url()).toContain(`video_ids=${videoId}`);
    await route.fulfill({ json: { state: "results", skipped_videos: [], results: [{
      video_id: videoId, video_title: "Product demo", frame_time_seconds: 20,
      frame_url: `/videos/${videoId}/frames/0`, playback_url: `/videos/${videoId}/media`,
      query_time_seconds: 0,
    }] } });
  });
  await page.route(`${apiOrigin}/videos/${videoId}/frames/0`, async (route) => {
    await route.fulfill({ body: png, contentType: "image/png" });
  });
  await page.goto("/");
  await page.locator(`.video-filters input[value="${videoId}"]`).check();
  await page.getByLabel("Screenshot or clip").setInputFiles({ name: "query.png", mimeType: "image/png", buffer: png });
  await expect(page.getByAltText("Image submitted for visual search")).toBeVisible();
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await expect(page.getByText("Similar sampled frame at 0:20")).toBeVisible();
  await expect(page.getByAltText("Matched frame from Product demo at 0:20")).toBeVisible();
  await page.getByRole("button", { name: "Play from this frame" }).click();
  await expect(page.getByText("Starts at 0:20 on the matched frame. Playback continues normally.")).toBeVisible();
});

test("visual query shows a validation failure without adding a library video", async ({ page }) => {
  await page.route(`${apiOrigin}/videos`, async (route) => {
    await route.fulfill({ json: [{
      id: videoId, title: "Product demo", duration_seconds: 42, status: "ready",
      current_step: null, error: null, transcript_state: "none", visual_state: "ready",
      visual_error: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }] });
  });
  await page.route(`${apiOrigin}/search/visual**`, async (route) => {
    await route.fulfill({ status: 422, json: { detail: "Use a valid JPEG or PNG image." } });
  });
  await page.goto("/");
  await page.getByLabel("Screenshot or clip").setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: Buffer.from("bad") });
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await expect(page.locator(".visual-query .inline-error")).toHaveText("Use a valid JPEG or PNG image.");
  await expect(page.locator(".video-row")).toHaveCount(1);
});

test("local image query reaches indexed media and seeks the original video", async ({ page }) => {
  const queryFile = process.env.PRISM_BROWSER_VISUAL_QUERY_FILE;
  const indexedId = process.env.PRISM_BROWSER_DEMO_ID;
  test.skip(!queryFile || !indexedId, "Set a local source image and indexed demo ID");
  const evalOrigin = process.env.PRISM_BROWSER_VISUAL_API_ORIGIN;
  if (evalOrigin) {
    await page.addInitScript(({ from, to }) => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        if (typeof input === "string" && input.startsWith(`${from}/search/visual`)) {
          return originalFetch(input.replace(from, to), init);
        }
        return originalFetch(input, init);
      };
    }, { from: apiOrigin, to: evalOrigin });
  }
  await page.goto("/");
  await page.locator(`.video-filters input[value="${indexedId}"]`).check();
  await page.getByLabel("Screenshot or clip").setInputFiles(queryFile!);
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await expect(page.getByText(/possible visual moments?/)).toBeVisible();
  await page.getByRole("button", { name: "Play from this frame" }).first().click();
  const player = page.locator(".visual-query .player-panel video");
  await expect(player).toBeVisible();
  await expect.poll(async () => player.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(30);
});

test("local clip query identifies a sampled source view", async ({ page }) => {
  const queryFile = process.env.PRISM_BROWSER_VISUAL_CLIP_FILE;
  const indexedId = process.env.PRISM_BROWSER_DEMO_ID;
  const evalOrigin = process.env.PRISM_BROWSER_VISUAL_API_ORIGIN;
  test.skip(!queryFile || !indexedId || !evalOrigin, "Set a local clip, indexed demo ID, and updated API origin");
  await page.addInitScript(({ from, to }) => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      if (typeof input === "string" && input.startsWith(`${from}/search/visual`)) {
        return originalFetch(input.replace(from, to), init);
      }
      return originalFetch(input, init);
    };
  }, { from: apiOrigin, to: evalOrigin! });
  await page.goto("/");
  await page.locator(`.video-filters input[value="${indexedId}"]`).check();
  await page.getByLabel("Screenshot or clip").setInputFiles(queryFile!);
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await expect(page.getByText(/Matched query sample near/).first()).toBeVisible();
  await page.getByRole("button", { name: "Play from this frame" }).first().click();
  await expect(page.locator(".visual-query .player-panel video")).toBeVisible();
});
