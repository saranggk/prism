import { expect, test } from "@playwright/test";

const apiOrigin = process.env.PRISM_BROWSER_API_ORIGIN ?? "http://127.0.0.1:8000";
const videoId = process.env.PRISM_BROWSER_VIDEO_ID;
let collectionId = "";

test.afterEach(async ({ request }) => {
  if (!collectionId) return;
  await request.delete(`${apiOrigin}/collections/${collectionId}`, { headers: { "X-Prism-Request": "1" } });
  collectionId = "";
});

test("creates, edits, orders, and plays saved source ranges", async ({ page }) => {
  test.skip(!videoId, "Set PRISM_BROWSER_VIDEO_ID to a ready local video");
  const title = `Browser collection ${test.info().project.name} ${Date.now()}`;
  await page.route(`${apiOrigin}/search**`, async (route) => {
    await route.fulfill({ json: { state: "results", results: [{
      video_id: videoId, video_title: "Source video", start_seconds: 10,
      end_seconds: 13, excerpt: "A suggested moment", evidence: ["transcript"],
      preview_time_seconds: null, preview_url: null,
      playback_url: `/videos/${videoId}/media`,
    }], video_results: [], provisional: true } });
  });
  await page.goto("/");
  await page.getByLabel("New collection").fill(title);
  await page.getByRole("button", { name: "Create collection" }).click();
  await expect(page.getByRole("combobox", { name: "Collection", exact: true }).locator("option:checked")).toHaveText(title);
  collectionId = await page.getByRole("combobox", { name: "Collection", exact: true }).inputValue();

  const add = page.locator(".collection-add");
  await add.getByLabel("Source video").selectOption(videoId!);
  await add.getByLabel("Start (m:ss)").fill("0:01");
  await add.getByLabel("End (m:ss)").fill("0:03");
  await add.getByLabel("Note").fill("Manual range");
  await add.getByRole("button", { name: "Add to collection" }).click();
  await expect(page.locator(".collection-item")).toHaveCount(1);

  const first = page.locator(".collection-item").first();
  await first.getByRole("button", { name: "Play source" }).click();
  await expect(page.getByText(/Saved range 0:01–0:03/)).toBeVisible();
  await first.getByLabel("Start (m:ss)").fill("0:02");
  await first.getByLabel("End (m:ss)").fill("0:04");
  await first.getByLabel("Note").fill("Edited range");
  await first.getByRole("button", { name: "Save changes" }).click();
  await expect(first).toContainText("0:02–0:04");
  await expect(page.getByText(/Saved range 0:02–0:04/)).toBeVisible();

  await page.getByRole("searchbox", { name: "Search question" }).fill("suggested moment");
  await page.getByRole("button", { name: /^Search/ }).click();
  await page.getByRole("button", { name: "Save to collection" }).click();
  await add.getByLabel("Note").fill("Search range");
  await add.getByRole("button", { name: "Add to collection" }).click();
  await expect(page.locator(".collection-item")).toHaveCount(2);
  await page.locator(".collection-item").last().getByRole("button", { name: /Move .* earlier/ }).click();
  await expect(page.locator(".collection-item").first().getByLabel("Note")).toHaveValue("Search range");

  await page.reload();
  await page.getByRole("combobox", { name: "Collection", exact: true }).selectOption({ label: title });
  await expect(page.locator(".collection-item")).toHaveCount(2);
  await expect(page.locator(".collection-item").first().getByLabel("Note")).toHaveValue("Search range");
  await page.locator(".collection-item").first().getByRole("button", { name: "Play source" }).click();
  await expect(page.getByText(/Saved range 0:10–0:13/)).toBeVisible();
  await expect(page.locator(".collections video")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete collection" }).click();
  await expect(page.getByRole("combobox", { name: "Collection", exact: true }).locator(`option:has-text("${title}")`)).toHaveCount(0);
});

test("saves a visual frame as an editable source range", async ({ page }) => {
  test.skip(!videoId, "Set PRISM_BROWSER_VIDEO_ID to a ready local video");
  const title = `Visual collection ${test.info().project.name} ${Date.now()}`;
  await page.route(`${apiOrigin}/search/visual**`, async (route) => {
    await route.fulfill({ json: { state: "results", results: [{
      video_id: videoId, video_title: "Source video", frame_time_seconds: 20,
      frame_url: `/videos/${videoId}/frames/0`, playback_url: `/videos/${videoId}/media`,
      query_time_seconds: 0,
    }], skipped_videos: [] } });
  });
  await page.goto("/");
  await page.getByLabel("New collection").fill(title);
  await page.getByRole("button", { name: "Create collection" }).click();
  await expect(page.getByRole("combobox", { name: "Collection", exact: true }).locator("option:checked")).toHaveText(title);
  collectionId = await page.getByRole("combobox", { name: "Collection", exact: true }).inputValue();
  await page.getByLabel("Screenshot or clip").setInputFiles({
    name: "query.png", mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9YjQ7f8AAAAASUVORK5CYII=", "base64"),
  });
  await page.getByRole("button", { name: "Find similar moments" }).click();
  await page.getByRole("button", { name: "Save to collection" }).click();
  const add = page.locator(".collection-add");
  await expect(add.getByLabel("Start (m:ss)")).toHaveValue("0:17.5");
  await expect(add.getByLabel("End (m:ss)")).toHaveValue("0:22.5");
  await add.getByRole("button", { name: "Add to collection" }).click();
  await expect(page.locator(".collection-item")).toHaveCount(1);
  await expect(page.locator(".collection-item").first()).toContainText("0:17–0:22");
});
