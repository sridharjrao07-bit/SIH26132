// Machine codes -> human labels. Never render a raw code (API_CONTRACT §8 MatchItem.reasons).
// Unknown codes fall back to a neutral label: the sets are open on the server side.
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

export const MATCH_REASON: Record<string, MessageDescriptor> = {
  verified: msg`Verified buyer`,
  same_district: msg`Same district`,
  price_covers_ask: msg`Pays your asking price`,
  bid_below_ask: msg`Pays below your asking price`,
  volume_fit: msg`Wants this quantity`,
  bid_low: msg`Low price`,
  reliability_high: msg`Pays reliably`,
  reliability_medium: msg`Payment record: average`,
  reliability_low: msg`Payment record: poor`,
  distance_ok: msg`Close by`,
  distance_far: msg`Far away`,
  over_demand: msg`More than they need`,
  grade_match: msg`Grade matches`,
};

export const LOT_STATUS: Record<string, MessageDescriptor> = {
  open: msg`Open`, offered: msg`Offer received`, matched: msg`Deal agreed`, sold: msg`Sold`, withdrawn: msg`Withdrawn`,
};

export const OFFER_STATUS: Record<string, MessageDescriptor> = {
  pending: msg`Waiting`, accepted: msg`Accepted`, rejected: msg`Rejected`, expired: msg`Expired`,
};

export const PAYMENT_STATUS: Record<string, MessageDescriptor> = {
  pending: msg`Payment pending`, paid: msg`Paid`, failed: msg`Payment failed`, disputed: msg`Disputed`,
};

export const BOOKING_STATUS: Record<string, MessageDescriptor> = {
  requested: msg`Requested`, confirmed: msg`Confirmed`, completed: msg`Completed`, cancelled: msg`Cancelled`,
};

export const GRIEVANCE_CATEGORY: Record<string, MessageDescriptor> = {
  payment: msg`Payment`, quality: msg`Quality`, logistics: msg`Transport`, buyer: msg`Buyer`, other: msg`Other`,
};

export const GRIEVANCE_STATUS: Record<string, MessageDescriptor> = {
  open: msg`Complaint open`, in_progress: msg`Being handled`, resolved: msg`Resolved`, rejected: msg`Complaint rejected`,
};

export const LEDGER_EVENT: Record<string, MessageDescriptor> = {
  lot_created: msg`Lot listed`,
  offer_pending: msg`Offer made`, offer_accepted: msg`Offer accepted`, offer_rejected: msg`Offer rejected`, offer_expired: msg`Offer expired`,
  payment_pending: msg`Payment recorded`, payment_paid: msg`Payment received`, payment_failed: msg`Payment failed`, payment_disputed: msg`Payment disputed`,
  grievance_open: msg`Complaint raised`, grievance_in_progress: msg`Complaint being handled`, grievance_resolved: msg`Complaint resolved`, grievance_rejected: msg`Complaint rejected`,
  booking_requested: msg`Booking requested`, booking_confirmed: msg`Booking confirmed`, booking_completed: msg`Booking completed`, booking_cancelled: msg`Booking cancelled`,
};

export const BUYER_TYPE: Record<string, MessageDescriptor> = {
  trader: msg`Trader`, processor: msg`Processor`, institutional: msg`Institution`, fpo: msg`FPO`, digital: msg`Online buyer`,
};

export const UNKNOWN = msg`Other`;
export const label = (map: Record<string, MessageDescriptor>, code: string) => map[code] ?? UNKNOWN;
