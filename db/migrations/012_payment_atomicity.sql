-- =============================================================================
-- Migration 012: Payment / lot CHECKs + one pending payment per offer
-- Apply after 011. Skip if already applied.
-- =============================================================================

alter table public.payments drop constraint if exists chk_payments_amount_positive;
alter table public.payments
    add constraint chk_payments_amount_positive check (amount > 0);

alter table public.lots drop constraint if exists chk_lots_qty_positive;
alter table public.lots
    add constraint chk_lots_qty_positive check (quantity_qtl > 0);

-- Retries must not insert a second pending row for the same offer.
create unique index if not exists uq_payments_one_open_per_offer
    on public.payments (offer_id)
    where status in ('pending', 'paid');
