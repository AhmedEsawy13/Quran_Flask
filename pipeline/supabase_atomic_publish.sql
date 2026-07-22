-- Atomic publishing migration for existing Athar Supabase projects.
-- Safe to run repeatedly in Supabase SQL Editor.

create or replace function public.publish_editor_edition(
  p_edition text,
  p_actor_id uuid,
  p_actor_name text,
  p_expected_changes jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_changes jsonb;
  v_count integer;
begin
  if p_edition not in ('قطر', 'الكويت') then
    raise exception 'invalid publish edition' using errcode = '22023';
  end if;
  if p_expected_changes is null or jsonb_typeof(p_expected_changes) <> 'array' then
    raise exception 'expected publish snapshot is required' using errcode = '22023';
  end if;

  lock table public.editor_marks in share row exclusive mode;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'surah', d.surah,
        'ayah', d.ayah,
        'token_index', d.token_index,
        'old_symbol', coalesce(p.symbol, ''),
        'new_symbol', coalesce(d.symbol, '')
      ) order by d.surah, d.ayah, d.token_index
    ),
    '[]'::jsonb
  )
  into v_changes
  from public.editor_marks d
  left join public.editor_marks p
    on p.edition = d.edition
   and p.surah = d.surah
   and p.ayah = d.ayah
   and p.token_index = d.token_index
   and p.status = 'published'
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') <> coalesce(p.symbol, '');

  if p_expected_changes <> v_changes then
    raise exception 'publish snapshot changed; refresh pending changes'
      using errcode = '40001';
  end if;

  v_count := jsonb_array_length(v_changes);

  delete from public.editor_marks p
  using public.editor_marks d
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') = ''
    and p.edition = d.edition
    and p.surah = d.surah
    and p.ayah = d.ayah
    and p.token_index = d.token_index
    and p.status = 'published'
    and coalesce(p.symbol, '') <> '';

  insert into public.editor_marks (
    edition, surah, ayah, token_index, status, symbol,
    word_text, updated_by, updated_at
  )
  select
    d.edition, d.surah, d.ayah, d.token_index, 'published', d.symbol,
    d.word_text, p_actor_id, now()
  from public.editor_marks d
  left join public.editor_marks p
    on p.edition = d.edition
   and p.surah = d.surah
   and p.ayah = d.ayah
   and p.token_index = d.token_index
   and p.status = 'published'
  where d.edition = p_edition
    and d.status = 'draft'
    and coalesce(d.symbol, '') <> ''
    and coalesce(d.symbol, '') <> coalesce(p.symbol, '')
  on conflict (edition, surah, ayah, token_index, status)
  do update set
    symbol = excluded.symbol,
    word_text = excluded.word_text,
    updated_by = excluded.updated_by,
    updated_at = excluded.updated_at;

  insert into public.editor_audit (
    actor_id, actor_name, action, edition, meta
  ) values (
    p_actor_id, p_actor_name, 'publish', p_edition,
    jsonb_build_object('count', v_count, 'changes', v_changes)
  );

  return jsonb_build_object(
    'edition', p_edition,
    'published', v_count,
    'changes', v_changes
  );
end;
$$;

revoke all on function public.publish_editor_edition(text, uuid, text, jsonb)
  from public;
grant execute on function public.publish_editor_edition(text, uuid, text, jsonb)
  to service_role;
