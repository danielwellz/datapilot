import { HttpParams } from '@angular/common/http';

/**
 * A query object (such as `OrderListQuery`) as HTTP parameters. Absent
 * fields are left out and a list repeats its key for each value. Typed as
 * `object` because the query interfaces have no index signature.
 */
export function toHttpParams(query: object): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(query) as [string, unknown][]) {
    if (Array.isArray(value)) {
      for (const item of value as readonly string[]) {
        params = params.append(key, item);
      }
    } else if (typeof value === 'string' || typeof value === 'number') {
      params = params.set(key, value);
    }
  }
  return params;
}
