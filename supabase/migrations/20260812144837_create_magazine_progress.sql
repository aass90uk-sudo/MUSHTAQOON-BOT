/*
# Create magazine_progress table (single-tenant, no auth)

1. New Tables
- `magazine_progress`
  - `id` (int, primary key, fixed at 1 — single row for this bot)
  - `next_page` (int, not null — the next page number to publish)
  - `finished` (boolean, not null, default false — whether the magazine is complete)
  - `updated_at` (timestamptz — when the progress was last saved)
2. Security
- Enable RLS on `magazine_progress`.
- Allow anon + authenticated full CRUD because this is a single-bot app with no sign-in.
3. Important Notes
- The bot uses the anon key to read and write its progress.
- Only one row (id = 1) is ever used; `upsert` keeps it simple.
*/

CREATE TABLE IF NOT EXISTS magazine_progress (
  id int PRIMARY KEY DEFAULT 1,
  next_page int NOT NULL,
  finished boolean NOT NULL DEFAULT false,
  updated_at timestamptz DEFAULT now()
);

ALTER TABLE magazine_progress ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_magazine_progress" ON magazine_progress;
CREATE POLICY "anon_select_magazine_progress" ON magazine_progress
  FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "anon_insert_magazine_progress" ON magazine_progress;
CREATE POLICY "anon_insert_magazine_progress" ON magazine_progress
  FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "anon_update_magazine_progress" ON magazine_progress;
CREATE POLICY "anon_update_magazine_progress" ON magazine_progress
  FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_delete_magazine_progress" ON magazine_progress;
CREATE POLICY "anon_delete_magazine_progress" ON magazine_progress
  FOR DELETE TO anon, authenticated USING (true);

-- Seed the initial row so the bot starts at page 9 on first build
INSERT INTO magazine_progress (id, next_page, finished)
VALUES (1, 9, false)
ON CONFLICT (id) DO NOTHING;
