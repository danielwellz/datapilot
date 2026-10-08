# 5. Keyset pagination with signed cursors

- Status: Accepted
- Date: 2026-10-08

## Context

The orders explorer pages through about 2 million orders, newest first or by total, with any combination of filters. Analysts scroll far: the API must stay fast on page 40,000 as on page 1. New orders arrive while someone is paging, and both sort values repeat often: in the full dataset, 29,052 `created_at` seconds belong to more than one order, and the 2 million totals take only 10,078 distinct values.

The options considered were:

- **`LIMIT`/`OFFSET`**: simple, and it allows jumping to page N. But PostgreSQL must produce and throw away every skipped row, so page N costs O(N): fetching the page after row 1,000,000 that way took 484 ms without indexes and still 303 ms with them (see `docs/performance.md`). Rows inserted or deleted while a client is paging also shift every later page, which gives duplicates or gaps.
- **Keyset (seek) pagination on the sort value alone**: fast, but wrong under ties. When a page ends inside a group of equal values, `WHERE created_at < :last` skips the rest of the group.
- **Keyset pagination on (sort value, id)**: the option chosen here.
- **Server-side cursors or snapshots**: they hold a transaction or memory per client between requests, which a stateless HTTP API should not do.

## Decision

**Ordering.** Every list query orders by `(sort column DESC, id DESC)`. `id` is unique, so the order is total: every row has exactly one position, even among rows with equal sort values.

**Seek condition.** The next page is the rows after the last row of the previous page:

```sql
WHERE (created_at, id) < (:last_created_at, :last_id)
ORDER BY created_at DESC, id DESC
LIMIT :limit + 1
```

The row-value comparison means "earlier timestamp, or the same timestamp and a smaller id". PostgreSQL turns it directly into a range on the index `(created_at, id)`, so the page is read from the index wherever it starts. The extra row tells the server whether a next page exists without a `COUNT(*)`; the response therefore has no total count.

**Cursor contents.** `next_cursor` is URL-safe base64 of a small JSON document: a format version, the sort, the last row's sort value and id, and a fingerprint (a 64-bit BLAKE2b hash) of the normalized filters. An HMAC-SHA256 tag follows, with a key derived from `SECRET_KEY` for this one purpose (`backend/app/services/cursors.py`).

**Validation.** The server answers **400 `invalid_cursor`** when a cursor:

- is malformed, too long, or fails the signature check (edited or made up);
- has an unknown format version or invalid contents;
- was issued for another sort or other filters.

Without the last check, a cursor reused with other filters would quietly start the new result in the wrong place. The page size may change between requests, and the same statuses in a different order count as the same filters.

**What clients do.** They treat the cursor as opaque, send it back unchanged with the same filters and sort, and start from the first page when they get `invalid_cursor`.

## Consequences

- Every page costs about the same as the first one (measured in `docs/performance.md`), and a walk over all pages returns each matching order exactly once. `backend/tests/integration/test_orders_list.py` proves it on deliberately tied data for both sorts, several page sizes and several filter sets.
- Clients cannot jump to page N or show "page 3 of 80,000". The explorer uses "next" and "back to first page", which suits browsing a live, very large list.
- Each supported sort needs an index that starts with its sort column and ends with `id`. Adding a sort later means adding such an index.
- Rotating `SECRET_KEY` invalidates open cursors. Clients see `invalid_cursor` once and start again from the first page.
- Rows inserted after a client started paging appear only if they sort after its position. For an explorer of past orders, that is the expected behaviour.
