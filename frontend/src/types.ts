// Mirrors backend/app/panel/schema.py. Keep the two in sync.

// --- Panel analysis output --------------------------------------------------

export interface TranscriptRef {
  speaker: string | null;
  quote: string | null;
  absent: boolean; // true when the finding is an ABSENCE — the room never raised it
}

export type RationaleStatus = "stated" | "not_stated";
export type OperabilityStatus = "not_applicable" | "cleared" | "not_confirmed";

export interface Finding {
  issue: string;
  recommendation: string;
  recommendation_grade: string | null;
  match_confidence: number; // 0..1 — the panel's certainty it fits THIS patient
  evidence_ref: string;
  rationale_status: RationaleStatus;
  patient_facing_note: string;
  live_question: string;
  source_specialist: string;
  proposes_procedure: boolean;
  operability_status: OperabilityStatus;
  transcript_ref: TranscriptRef | null;
}

export interface ActionItem {
  action: string;
  owner: string;
  deadline: string | null;
  linked_finding: string | null;
}

export type ClaimStance = "recommend" | "caution" | "oppose" | "defer";

export interface Claim {
  about: string;
  stance: ClaimStance;
  statement: string;
}

export interface SpecialistOpinion {
  specialist: string;
  title: string;
  summary: string;
  findings: Finding[];
  claims: Claim[];
  needs: string[];
  confidence: number;
}

export interface Conflict {
  kind: "contradiction" | "dependency";
  topic: string;
  description: string;
  specialists: string[];
  resolved: boolean;
  resolution: string | null;
}

export interface DeliberationEntry {
  round: number;
  topic: string;
  prompt_to: string;
  opposing_claim: string;
  response: string;
}

export interface PanelResult {
  case_id: string;
  specialists_consulted: string[];
  findings: Finding[];
  action_ledger: ActionItem[];
  conflicts: Conflict[];
  deliberation: DeliberationEntry[];
  rounds: number;
  opinions: SpecialistOpinion[];
  truncated: boolean;
}

// --- Patient data browser (data/cases/<case_id>/<specialty>/*.md) -------------

export interface Document {
  doc_id: string;
  folder: string;
  filename: string;
  title: string;
  date: string | null;
  body: string;
}

export interface Folder {
  name: string;
  label: string;
  documents: Document[];
}

export interface CaseSummary {
  case_id: string;
  cancer_type: string | null;
  patient_ref: string | null;
  line_of_therapy: string | null;
  board_date: string | null;
  folder_names: string[];
  document_count: number;
}

export interface CaseDetail extends CaseSummary {
  folders: Folder[];
  transcript: string | null;
}
