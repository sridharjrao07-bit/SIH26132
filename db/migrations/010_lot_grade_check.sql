-- =============================================================================
-- Migration 010: Lot grade CHECK (FAQ / General / Special)
--
-- API already rejects unknown grades. This pins the same rule in Postgres
-- after 008 created lots.grade as unconstrained text.
-- Apply after 009_logistics_bookings.sql.
-- =============================================================================

update public.lots
set grade = 'General'
where grade is null or grade not in ('FAQ', 'General', 'Special');

alter table public.lots drop constraint if exists lots_grade_check;
alter table public.lots
    add constraint lots_grade_check
        check (grade in ('FAQ', 'General', 'Special'));
