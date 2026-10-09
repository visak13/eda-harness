import { describe, it, expect } from "vitest";
import { personName } from "./usePersonName";
import { docTitle } from "../pages/knowledgeShared";
import type { PersonRow } from "../api/types";

// S12-ui2 (qa m-da89ef8294 item 6): raw ids where words belong.
const guest: PersonRow = { id: "guest-bc795c7001", handle: "qaguest", type: "human", role: "guest", seat_ticket: null, seat_state: null, label: "person", self: false };

describe("personName (S12-ui2)", () => {
  it("names a guest as People does, never by its participant id", () => {
    expect(personName("guest-bc795c7001", [guest])).toBe("ext:qaguest");
    expect(personName("@qaguest", [guest])).toBe("ext:qaguest");
  });
  it("keeps a seat's role and a person's handle", () => {
    expect(personName("engineer.s-2cdb1ba03b", [guest])).toBe("engineer");
    expect(personName("owner", undefined)).toBe("owner");
  });
});

describe("docTitle (S12-ui2)", () => {
  it("drops the kind prefix the chip already shows", () => {
    expect(docTitle("strategy_hl: walking-skeleton")).toBe("walking-skeleton");
    expect(docTitle("strategy_ll: python craft")).toBe("python craft");
    expect(docTitle("Domain: billing")).toBe("billing");
    expect(docTitle("Plain title: with a colon")).toBe("Plain title: with a colon");
  });
});
