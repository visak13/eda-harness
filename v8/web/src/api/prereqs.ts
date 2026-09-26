import { api, postJson } from "./client";

// The setup wizard's "Your tools" step (t-08612be1b0): rows of the one prerequisites manifest
// (edp_contracts.prereqs), served by /v1/admin/setup/prereqs.

export interface PrereqJob { state: "running" | "done" | "failed"; exit?: number | null; output?: string | null; by?: string }

export interface PrereqRow {
  name: string;
  need: "required" | "harness" | "optional" | "default";
  feature: string;
  purpose: string;
  state: "ok" | "missing" | "outdated" | "off";
  path: string | null;
  version: string | null;
  min_version: string;
  fix: string;
  installable: boolean;
  docs: string;
  login?: string;
  signed_in?: boolean | null;
  job: PrereqJob | null;
}

export interface PrereqsView {
  os: string;
  rows: PrereqRow[];
  harness_ok: boolean;
  bundled: { name: string; why: string }[];
  not_needed: { name: string; why: string }[];
}

export const getPrereqs = () => api<PrereqsView>("/v1/admin/setup/prereqs");
export const installPrereq = (name: string) =>
  postJson<PrereqJob>(`/v1/admin/setup/prereqs/${encodeURIComponent(name)}/install`, {});
