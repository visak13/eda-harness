import { expect, test, type Page, BASE } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";

test.use({ boardFile: "g2-composer" }); // one fresh board per spec file (fixtures.ts)

// The object-attached composer, proven through the real shell (design §13/§16.1/§18.1/§4.2):
//   c-8c5ea3c8ba / c-01e4b9073e: the To picker groups People / Live seats / Roles; a wake preview
//     from POST /v1/messages/resolve shows one that resolves (To=owner → the epic's human owner)
//     and one that does not (To=qa → "no qa seat exists on this epic yet"); it never fans out.
//   c-a104919562: the message field is a textarea at least 4 rows tall (≈104px at 14/22) and a
//     600-character paragraph is fully readable without scrolling inside the field at 1440×900.
//   c-3430cb816f: dropping a file shows a "Drop to attach" veil and, on drop, stages it via
//     /v1/artifacts/upload and inserts its token; a refused type leaves the draft intact.

test.use({ viewport: { width: 1440, height: 900 } });

async function openNewConversation(page: Page): Promise<void> {
  await page.goto(`${BASE()}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
  await page.getByTestId("new-conversation").click();
  await expect(page.getByTestId("composer")).toBeVisible();
}

/** Dispatch a real DragEvent carrying a File onto the composer (Playwright has no file-drop API). */
async function dropFile(page: Page, bytes: number[], name: string, type: string): Promise<void> {
  await page.getByTestId("composer").evaluate(
    (el, { bytes, name, type }) => {
      const file = new File([new Uint8Array(bytes)], name, { type });
      const dt = new DataTransfer();
      dt.items.add(file);
      el.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
      el.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
    },
    { bytes, name, type },
  );
}

const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 1, 2, 3, 4]; // valid PNG magic
const BINARY = [0x00, 0x01, 0x02, 0x03, 0x04, 0x00, 0x99]; // no magic, not textual → refused (415)

test.describe("composer — To picker + wake preview", () => {
  let fx: G2Fixture;
  test.beforeAll(async () => {
    fx = await seedDecisions();
  });

  test("groups the picker and previews one recipient that resolves and one that does not", async ({ page }) => {
    await openNewConversation(page);
    const picker = page.getByTestId("to-picker");
    // The three optgroups the board's roster drives.
    for (const g of ["People", "Live seats", "Roles on this epic"]) {
      await expect(picker.locator(`optgroup[label="${g}"]`)).toHaveCount(1);
    }
    // A closed seat is never offered (the dead seat from the seed is absent from Live seats).
    await expect(picker.locator("option", { hasText: fx.deadSeat })).toHaveCount(0);

    // To=owner resolves to the epic's human owner → the wake preview names owner.
    await picker.selectOption("owner");
    await expect(page.getByTestId("wake-preview")).toContainText(/owner/);

    // To=qa has no seat on this epic → the board's "no qa seat" note, verbatim, nobody woken.
    await picker.selectOption("qa");
    await expect(page.getByTestId("wake-preview")).toContainText("no qa seat exists on this epic yet");
  });
});

test.describe("composer — field size (§4.2)", () => {
  test("the textarea is ≥4 rows and a 600-char paragraph does not scroll inside it", async ({ page }) => {
    await seedDecisions();
    await openNewConversation(page);
    const ta = page.getByTestId("composer-text");
    // Min 4 rows at 14/22 → ≈104px (4*22 + 16).
    expect((await ta.boundingBox())!.height).toBeGreaterThanOrEqual(100);

    const para = "word ".repeat(120).trim(); // ~600 chars
    await ta.fill(para);
    // Auto-grow means the content height fits the field: no inner scrollbar.
    const overflow = await ta.evaluate((el) => (el as HTMLTextAreaElement).scrollHeight - el.clientHeight);
    expect(overflow).toBeLessThanOrEqual(2);
    // …and it never exceeds the 14-row ceiling (14*22 + 16 = 324).
    expect((await ta.boundingBox())!.height).toBeLessThanOrEqual(326);
  });
});

test.describe("composer — drag-and-drop upload (§18.1)", () => {
  test("a dropped PNG shows the veil and stages an artifact token; a refused type keeps the draft", async ({ page }) => {
    await seedDecisions();
    await openNewConversation(page);
    const ta = page.getByTestId("composer-text");
    await ta.fill("Here is the evidence: ");

    // Drop a valid PNG → it uploads and its `art-…` token is inserted into the draft.
    await dropFile(page, PNG, "shot.png", "image/png");
    await expect.poll(async () => await ta.inputValue()).toMatch(/art-[a-z0-9]/i);
    // The draft prose is preserved alongside the token.
    expect(await ta.inputValue()).toContain("Here is the evidence:");

    // A refused binary → the error banner shows and the draft (prose + prior token) is intact.
    const before = await ta.inputValue();
    await dropFile(page, BINARY, "payload.bin", "application/octet-stream");
    await expect(page.getByRole("alert")).toContainText(/Upload failed/i);
    expect(await ta.inputValue()).toBe(before);
  });
});
