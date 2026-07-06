import { api } from "../api/client";
import type { Proposal } from "../api/types";
export const dismissProposalAction = (p: Proposal) => api.dismissProposal(p.id);
