// Client-side preview of the tally rules in section 9.6 of backend/SPEC.md.
// Used ONLY for the "current status" widget, never as authoritative.

import type {
  Question,
  StoredResponse,
  VoteResponse,
  LazyConsensusResponse,
} from "./types";

// Minimum binding +1 votes required for unanimous_approval and
// majority_approval to resolve as "approved". Mirrors
// ``MIN_BINDING_PLUS_ONE`` in ``cap_backend/tally.py``.
export const MIN_BINDING_PLUS_ONE = 3;

function latestPerVoter(responses: StoredResponse[]): StoredResponse[] {
  const byVoter = new Map<string, StoredResponse>();
  for (const r of responses) {
    const prev = byVoter.get(r.voter);
    if (!prev || Date.parse(r.created_at) > Date.parse(prev.created_at)) {
      byVoter.set(r.voter, r);
    }
  }
  return Array.from(byVoter.values());
}

export interface UnanimousPreview {
  kind: "unanimous_approval";
  vetoes: { voter: string; comment: string | null }[];
  bindingPlus1: number;
  minBindingPlus1: number;
  approved: boolean;
}

export interface MajorityPreview {
  kind: "majority_approval";
  binding: { plus1: number; plus0: number; minus0: number; minus1: number };
  nonbinding: { plus1: number; plus0: number; minus0: number; minus1: number };
  minBindingPlus1: number;
  approved: boolean;
}

export interface SimpleMajorityPreview {
  kind: "simple_majority";
  binding: { plus1: number; plus0: number; minus0: number; minus1: number };
  nonbinding: { plus1: number; plus0: number; minus0: number; minus1: number };
  approved: boolean;
}

export interface LazyPreview {
  kind: "lazy_consensus";
  objections: { voter: string; comment: string | null }[];
  approved: boolean;
}

export type TallyPreview =
  | UnanimousPreview
  | MajorityPreview
  | SimpleMajorityPreview
  | LazyPreview;

export function previewTally(
  question: Question,
  responses: StoredResponse[],
): TallyPreview {
  const latest = latestPerVoter(responses);

  if (question.approval_type === "unanimous_approval") {
    const vetoes = latest
      .filter((r) => r.is_veto)
      .map((r) => ({ voter: r.voter, comment: r.comment ?? null }));
    let bindingPlus1 = 0;
    for (const r of latest) {
      if (
        r.response.kind === "vote" &&
        (r.response as VoteResponse).value === "+1" &&
        r.is_binding
      ) {
        bindingPlus1++;
      }
    }
    return {
      kind: "unanimous_approval",
      vetoes,
      bindingPlus1,
      minBindingPlus1: MIN_BINDING_PLUS_ONE,
      approved:
        vetoes.length === 0 && bindingPlus1 >= MIN_BINDING_PLUS_ONE,
    };
  }

  if (
    question.approval_type === "majority_approval" ||
    question.approval_type === "simple_majority"
  ) {
    const counts = {
      plus1: 0,
      plus0: 0,
      minus0: 0,
      minus1: 0,
    };
    const binding = { ...counts };
    const nonbinding = { ...counts };
    for (const r of latest) {
      if (r.response.kind !== "vote") continue;
      const v = r.response as VoteResponse;
      const bucket = r.is_binding ? binding : nonbinding;
      switch (v.value) {
        case "+1":
          bucket.plus1++;
          break;
        case "+0":
          bucket.plus0++;
          break;
        case "-0":
          bucket.minus0++;
          break;
        case "-1":
          bucket.minus1++;
          break;
      }
    }
    if (question.approval_type === "simple_majority") {
      return {
        kind: "simple_majority",
        binding,
        nonbinding,
        approved: binding.plus1 > binding.minus1,
      };
    }
    return {
      kind: "majority_approval",
      binding,
      nonbinding,
      minBindingPlus1: MIN_BINDING_PLUS_ONE,
      approved:
        binding.plus1 >= MIN_BINDING_PLUS_ONE &&
        binding.plus1 > binding.minus1,
    };
  }

  const objections = latest
    .filter((r) => {
      if (r.response.kind === "lazy_consensus") {
        return (r.response as LazyConsensusResponse).objection;
      }
      if (r.response.kind === "vote") {
        return (r.response as VoteResponse).value === "-1";
      }
      return false;
    })
    .map((r) => ({ voter: r.voter, comment: r.comment ?? null }));
  return {
    kind: "lazy_consensus",
    objections,
    approved: objections.length === 0,
  };
}
